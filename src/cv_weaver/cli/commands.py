"""CLI commands for cv-weaver.

Entry point: `cv-weaver <command> [args]`
"""

import argparse
import sys
from pathlib import Path

from cv_weaver.config import load_settings
from cv_weaver.generator.engine import GeneratorEngine
from cv_weaver.llm_client.instructor_wrapper import create_instructor_client
from cv_weaver.models.enums import GenerationLevel, Status
from cv_weaver.storage.db import get_connection, init_db
from cv_weaver.storage.repository import CVPointRepository


def _resolve_knowledge_base_file(file_id: str, settings) -> tuple[Path, str]:
    """Find a knowledge base file by file_id and determine its source_type.

    Returns:
        (file_path, source_type) where source_type is "experience" or "project".
    """
    kb = Path(settings.knowledge_base_path)

    # Try experience/
    exp_dir = kb / "experience"
    for f in exp_dir.glob("*.md"):
        if f.stem == file_id:
            return f, "experience"

    # Try projects/
    proj_dir = kb / "projects"
    for f in proj_dir.glob("*.md"):
        if f.stem == file_id:
            return f, "project"

    raise FileNotFoundError(
        f"No knowledge base file found for '{file_id}' in {kb}"
    )


def cmd_generate(args) -> int:
    """Run L1 generation for one knowledge base file."""
    settings = load_settings()
    db_path = Path(settings.database_path)
    init_db(db_path)

    conn = get_connection(db_path)
    repo = CVPointRepository(conn)
    client = create_instructor_client(settings)
    engine = GeneratorEngine(client, repo, settings)

    try:
        file_path, source_type = _resolve_knowledge_base_file(args.file_id, settings)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Generating CV points for {args.file_id} ({source_type})...")
    print(f"File: {file_path}\n")

    result = engine.generate_from_file(file_path, source_type)

    print(f"\n✅ Generation complete for {result.file_id}")
    print(f"   Stories processed: {len(result.story_results)}")
    print(f"   Total points generated: {result.total_points}")
    print(f"   Total QnA rounds: {result.total_qna_rounds}")

    for sr in result.story_results:
        print(f"\n   Story: {sr.story_title}")
        for cr in sr.candidates:
            bullet = cr.point.rendered_bullet[:60]
            conv = "✓" if cr.converged else "✗"
            print(
                f"     [{conv}] {bullet}... "
                f"(impact={cr.evaluation.impact_score}, "
                f"ats={cr.evaluation.ats_score}, "
                f"complete={cr.evaluation.completeness_score}, "
                f"qna={cr.qna_rounds})"
            )

    conn.close()
    return 0


def cmd_points_list(args) -> int:
    """List CV points from the database with optional filters."""
    settings = load_settings()
    db_path = Path(settings.database_path)

    if not db_path.exists():
        print("Error: Database not found. Run 'cv-weaver generate' first.", file=sys.stderr)
        return 1

    conn = get_connection(db_path)
    repo = CVPointRepository(conn)

    points = []
    if args.source:
        points = repo.list_by_source(args.source)
    elif args.status:
        points = repo.list_by_status(args.status)
    elif args.level:
        points = repo.list_by_generation_level(args.level)
    else:
        # Default: list all draft points
        points = repo.list_by_status(Status.DRAFT)

    if not points:
        print("No points found matching the criteria.")
        conn.close()
        return 0

    print(f"{'ID':<36} {'Source':<20} {'Level':<4} {'Status':<10} {'Score':<8} {'Bullet'}")
    print("-" * 120)
    for p in points:
        score_str = f"{p.scores.impact_score}/{p.scores.ats_score}/{p.scores.completeness_score}"
        bullet = p.rendered_bullet[:50] + "..." if len(p.rendered_bullet) > 50 else p.rendered_bullet
        print(
            f"{p.id:<36} {p.source.file_id:<20} {p.generation_level.value:<4} "
            f"{p.classification.status.value:<10} {score_str:<8} {bullet}"
        )

    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="cv-weaver",
        description="AI-powered CV point generator and manager",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # generate
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate L1 CV points from a knowledge base file",
    )
    gen_parser.add_argument("file_id", help="File ID (e.g., 01_tata-neu)")
    gen_parser.set_defaults(func=cmd_generate)

    # points list
    points_parser = subparsers.add_parser("points", help="Manage CV points")
    points_sub = points_parser.add_subparsers(dest="points_cmd")

    list_parser = points_sub.add_parser("list", help="List CV points")
    list_parser.add_argument("--source", help="Filter by source file ID")
    list_parser.add_argument("--status", choices=["draft", "approved", "archived"], help="Filter by status")
    list_parser.add_argument("--level", choices=["l1", "l2"], help="Filter by generation level")
    list_parser.set_defaults(func=cmd_points_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    # Handle nested subcommand dispatch
    if hasattr(args, "func"):
        return args.func(args)

    # If we reach here, a subcommand was given but no handler was set
    parser.print_help()
    return 1
