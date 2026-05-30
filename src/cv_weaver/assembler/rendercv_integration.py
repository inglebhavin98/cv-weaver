"""RenderCV integration: YAML validation and PDF rendering.

This module wraps RenderCV's Python API to convert an assembled YAML file into a
PDF. It is a thin, inspectable layer: we call named functions with known signatures
and catch structured exceptions.

Why Python API over CLI subprocess?
- Structured exceptions (RenderCVUserValidationError) contain YAML line numbers.
- No shell escaping or temp file race conditions.
- The pipeline is still fully visible: validate → typst → pdf.
"""

from pathlib import Path
from typing import Optional

from rendercv.exception import (
    RenderCVUserError,
    RenderCVUserValidationError,
)
from rendercv.renderer.pdf_png import generate_pdf
from rendercv.renderer.typst import generate_typst
from rendercv.schema.rendercv_model_builder import (
    build_rendercv_dictionary_and_model,
)


class RenderCVError(Exception):
    """Wrapper for RenderCV exceptions with context."""

    def __init__(self, message: str, original: Optional[Exception] = None):
        super().__init__(message)
        self.original = original


def render_pdf(yaml_path: Path) -> Path:
    """Render a RenderCV-compatible YAML file to PDF.

    Pipeline:
        1. Read YAML content from disk.
        2. Validate via RenderCV's Pydantic model builder.
        3. Generate Typst intermediate file.
        4. Compile Typst to PDF.

    Args:
        yaml_path: Path to the assembled RenderCV YAML file.

    Returns:
        Path to the generated PDF file.

    Raises:
        RenderCVError: If validation fails, rendering fails, or the typst binary is missing.
    """
    try:
        yaml_content = yaml_path.read_text(encoding="utf-8")
    except OSError as e:
        raise RenderCVError(f"Cannot read YAML file: {yaml_path}") from e

    # Step 1: Validate YAML against RenderCV schema
    try:
        _, rendercv_model = build_rendercv_dictionary_and_model(
            yaml_content,
            input_file_path=yaml_path,
        )
    except RenderCVUserValidationError as e:
        # RenderCV provides line/column metadata for each validation error.
        # We surface the first few to help the user debug the generated YAML.
        messages = []
        for err in e.validation_errors[:5]:
            loc = err.yaml_location
            loc_str = f"line {loc[0][0]}" if loc else "unknown location"
            messages.append(f"  [{loc_str}] {err.message}")
        raise RenderCVError(
            "RenderCV validation failed:\n" + "\n".join(messages),
            original=e,
        ) from e

    # Step 2: Generate Typst
    try:
        typst_path = generate_typst(rendercv_model)
    except RenderCVUserError as e:
        raise RenderCVError(f"Typst generation failed: {e}") from e

    if typst_path is None:
        raise RenderCVError(
            "Typst generation was skipped (dont_generate_typst is set)."
        )

    # Step 3: Compile PDF
    try:
        pdf_path = generate_pdf(rendercv_model, typst_path)
    except RenderCVUserError as e:
        raise RenderCVError(f"PDF compilation failed: {e}") from e

    if pdf_path is None:
        raise RenderCVError("PDF generation was skipped (dont_generate_pdf is set).")

    return pdf_path
