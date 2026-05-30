
ARCHITECTURE_DECISIONS
# cv-weaver Architecture Decisions

> **Purpose:** Living document for architectural recommendations, design rationale, and implementation status. Updated as decisions are made and features are implemented.
> **Last updated:** 2026-05-28

---

## Legend

- `[PENDING]` — Approved but not yet implemented
- `[DONE]` — Implemented and verified
- `[DEFERRED]` — Agreed to postpone until a later phase
- `[WONTFIX]` — Explicitly rejected after discussion

---

## ADR-001: Pydantic Schema as the SQLite Contract Bridge

**Status:** `[DONE]`

**Context:** The `CVPoint` Pydantic model exists in CLAUDE.md but is not yet in code. The SQLite schema in `db.py` mirrors it field-by-field but there is no shared source of truth.

**Decision:** Make `models/schemas.py` the single source of truth. Add `CVPoint.from_sqlite_row(row)` and `CVPoint.to_sqlite_dict()` so the repository layer never manually maps columns.

**Rationale:** Prevents drift between DB columns and application objects. A migration in the schema only requires changing the Pydantic model and the DDL in one place.

**Impact:** Medium. Affects `models/schemas.py`, `storage/repository.py`, `storage/db.py`.

---

## ADR-002: Repository Pattern with Context Managers

**Status:** `[DONE]`

**Context:** `storage/db.py` only provides `get_connection()`. There is no abstraction for CRUD operations.

**Decision:** Implement a `CVPointRepository` class in `storage/repository.py` that accepts a `sqlite3.Connection` and exposes typed methods: `insert(point)`, `get_by_id(id)`, `list_by_status(status)`, `list_by_source(file_id)`, `update_status(id, status)`, `list_approved_with_embeddings()`.

**Rationale:** Every other component depends on storage. A clean, injectable repository interface makes the system testable and prevents raw SQL from leaking into business logic.

**Impact:** High. Affects `storage/repository.py` and every consumer module.

---

## ADR-003: Config Module Uses Pydantic-Settings

**Status:** `[DONE]`

**Context:** `config.py` is empty. `.env.example` shows several configuration values.

**Decision:** Use a Pydantic `BaseSettings` subclass to validate configuration at startup. Fields: `ollama_base_url` (HttpUrl), `generation_model` (str), `embedding_model` (str), `redundancy_threshold` (float = 0.85), `database_path` (Path), `knowledge_base_path` (Path).

**Rationale:** Type-safe config prevents runtime failures from typos or missing env vars. Auto-complete and mypy checking are free bonuses.

**Impact:** Low. Affects `config.py` only.

---

## ADR-004: Markdown Parser Uses a Lightweight Grammar

**Status:** `[PENDING]`

**Context:** The chunking strategy in TECH_SPEC §2.2 relies on heuristics (double newlines, bullet markers, date anchors). This is fragile.

**Decision:** Define a lightweight marker convention for knowledge base markdown files. Chunks are separated by `## ` headers (or a custom `### ACHIEVEMENT` marker). The user controls chunking explicitly by how they organize their dump.

**Rationale:** Heuristics are hard to debug. Explicit boundaries make the parser deterministic and give the user control. The "append-only" constraint is still satisfied: new `##` sections are added at the bottom.

**Alternative considered:** Keep heuristics but add a `--preview-chunks` CLI command. Rejected because explicit markers are clearer for a learning project.

**Impact:** Medium. Affects `knowledge_base/parser.py` and the user's markdown authoring workflow.

---

## ADR-005: Instructor Wrapper Is a Thin Factory

**Status:** `[DONE]`

**Context:** `llm_client/instructor_wrapper.py` is empty.

**Decision:** Create a factory `create_instructor_client(base_url, api_key, model)` returning an `instructor.Client` configured for Ollama. Expose `chat_completion(prompt, response_model) -> BaseModel`.

**Rationale:** The `instructor` library wraps OpenAI-style clients. With Ollama, the base URL points to `http://localhost:11434/v1`. The wrapper handles URL setup, response_model passing, and InstructorRetryException mapping.

**Impact:** High. Affects `llm_client/instructor_wrapper.py` and every LLM-dependent module.

---

## ADR-006: Prompts Are Versioned String Assets

**Status:** `[PENDING]`

**Context:** `generator/prompts.py` is empty.

**Decision:** Store prompts as Jinja2 templates or multi-line string constants with version identifiers (e.g., `GENERATE_BULLET_V1`). Maintain a `PROMPT_REGISTRY` dict for benchmark iteration.

**Rationale:** Prompt engineering must be explicit and version-controllable. When running benchmarks, the prompt version is part of the config, enabling A/B testing.

**Impact:** Low. Affects `generator/prompts.py` and benchmark harnesses.

---

## ADR-007: Validator Returns Structured Feedback, Not Just Pass/Fail

**Status:** `[PENDING]`

**Context:** The validator checks rules but the retry loop needs context on *which* rules failed.

**Decision:** Make the validator return a `ValidationResult` dataclass: `passed` (bool), `violations` (list[str]), `suggested_fix` (str | None).

**Rationale:** A generic "try again" is less effective than "remove the pronoun 'I' and add a metric." Structured feedback improves the correction prompt.

**Impact:** Low. Affects `generator/validator.py` and `generator/engine.py`.

---

## ADR-008: RAG Embedding Matrix Is Cached In-Memory

**Status:** `[PENDING]`

**Context:** The RAG approach reloads all embeddings from SQLite on every query.

**Decision:** In `storage/embeddings.py`, implement an `EmbeddingIndex` class with a `_dirty` flag. The matrix is rebuilt only when a new point is approved.

**Rationale:** For a CLI-first tool, multiple queries per session are common. Re-loading 3MB from SQLite every time is unnecessary. A module-level singleton is acceptable since this is not a web server.

**Impact:** Medium. Affects `storage/embeddings.py` and `customizer/rag.py`.

---

## ADR-009: Assembler Uses PyYAML, Not String Concatenation

**Status:** `[PENDING]`

**Context:** `assembler/yaml_builder.py` is empty.

**Decision:** Build the RenderCV YAML as a Python dict and serialize with `yaml.safe_dump(..., sort_keys=False)`. Do NOT concatenate strings.

**Rationale:** PyYAML handles escaping, indentation, and multiline strings correctly. Manual string building is error-prone.

**Impact:** Low. Affects `assembler/yaml_builder.py`.

---

## ADR-010: `models/__init__.py` Re-Exports Public Types

**Status:** `[DONE]`

**Context:** `judge.py` imports `from cv_weaver.models.schemas import CVPoint`. With empty `__init__.py`, this works but is verbose.

**Decision:** In `models/__init__.py`, re-export all public types: `CVPoint`, `SourceContext`, `ExtendedContext`, `PointComponents`, `PointMetadata`, `Classification`, `PointScores`, etc.

**Rationale:** Standard Python package API pattern. Consumers import from `cv_weaver.models` instead of drilling into submodules.

**Impact:** Low. Affects `models/__init__.py` and all import statements.

---

## ADR-011: CLI Built with Click

**Status:** `[PENDING]`

**Context:** `cli/commands.py` is empty. `click` is already in `pyproject.toml`.

**Decision:** Use Click for the CLI. Proposed commands: `init`, `scan`, `generate`, `review`, `customize`, `assemble`, `benchmark`.

**Rationale:** Click provides automatic `--help`, type conversion, and command grouping. More ergonomic than argparse for multi-command CLIs.

**Impact:** Medium. Affects `cli/commands.py`, `cli/interface.py`, `main.py`.

---

## ADR-012: Test Strategy — Unit for Rules, Integration for Pipeline

**Status:** `[PENDING]`

**Context:** Tests are scaffolded but empty.

**Decision:**
- **Unit tests:** Test validator edge cases (pronouns, 200-char limit, empty metrics).
- **Integration tests:** Use `:memory:` SQLite and mock LLM client with deterministic responses. Test the full pipeline.
- **Fixtures:** Create `tests/fixtures/sample_exp.md` with realistic structured header + dump.

**Rationale:** The generator depends on an external LLM (non-deterministic, slow). Unit tests cover deterministic logic. Integration tests mock the LLM boundary.

**Impact:** Medium. Affects `tests/` directory.

---

## ADR-013: Editable Install + venv Wiring

**Status:** `[PENDING]`

**Context:** Project is scaffolded but not yet installable.

**Decision:** The setup command is `pip install -e ".[dev]"`. Document this in `README.md`.

**Rationale:** Wires `src/` into the Python path so `import cv_weaver` works from anywhere in the project.

**Impact:** Low. Affects `README.md` and user onboarding.

---

## ADR-014: Benchmark Harness Needs Ground-Truth Fixtures

**Status:** `[PENDING]`

**Context:** Benchmark scripts are empty.

**Decision:** Before writing benchmark code, create `benchmarks/fixtures/` with:
- `gold_points.jsonl`: 10–20 raw dump chunks paired with human-written "gold" CV points.
- `jd_queries.jsonl`: 5 job descriptions with labeled relevant point IDs.

**Rationale:** Benchmarks without ground truth measure noise, not quality. Labeled data is required to compute the metrics in TECH_SPEC §4.

**Impact:** Low. Affects `benchmarks/` directory and user curation effort.

---

## ADR-015: `has_metrics` Flag Is Derived, Not Stored

**Status:** `[DONE]`

**Context:** `PointScores.has_metrics` was a boolean while `PointMetadata.impact_metrics` is a list. Keeping both creates a sync hazard.

**Decision:** Remove `has_metrics` from `PointScores` entirely. Add it as a Pydantic V2 `@computed_field` on `CVPoint` (`len(self.metadata.impact_metrics) > 0`). Remove the boolean from the SQLite schema.

**Rationale:** Simpler schema, single source of truth. The distinction "user explicitly confirmed no metrics" vs "metrics were never asked" is not currently a requirement.

**Alternative considered:** Keep the boolean if we later need to track explicit confirmation. Rejected for now; can be added later if needed.

**Impact:** Low. Affects `models/schemas.py` and `storage/db.py`.

---

## ADR-016: Domain Tags Use a Controlled Taxonomy

**Status:** `[PENDING]`

**Context:** `domain_tags` are currently free-form strings.

**Decision:** Create `data/domain_taxonomy.yaml` with a controlled vocabulary (e.g., `fintech`, `backend_engineering`, `ml_platform`). Load it into the CLI for autocomplete.

**Rationale:** Free-form tags lead to inconsistencies (`fintech` vs `fin-tech` vs `finance`). A taxonomy is lightweight and prevents drift.

**Impact:** Low. Affects `data/domain_taxonomy.yaml` and CLI autocomplete.

---

## ADR-017: SQLite JSON1 Extension for Array Filtering

**Status:** `[PENDING]`

**Context:** Domain tag filtering is done in Python by loading JSON arrays and intersecting sets.

**Decision:** Use SQLite's built-in JSON1 extension for queries where possible. Test for JSON1 availability at startup; fall back to Python filtering if unavailable.

**Rationale:** Moves filtering to the database, which is faster and keeps the repository layer cleaner. Modern Python SQLite builds have JSON1 enabled by default.

**Impact:** Low. Affects `storage/repository.py` and `storage/db.py`.

---

## ADR-018: Consolidate Static Info into `profile.yaml`

**Status:** `[PENDING]`

**Context:** The design doc currently has a `static-sections/` folder for Tier 2 content (education, publications, patents, talks, honors). This adds file sprawl and requires the assembler to read from multiple files.

**Decision:** Move all semi-static sections into `profile.yaml` as structured sub-documents. Remove `static-sections/` entirely. The assembler reads Tier 1 and Tier 2 from a single file.

**Rationale:** Fewer files to manage, a single entry point for static data, and simpler assembler logic. `profile.yaml` is already the entry point for personal info; extending it keeps the knowledge base flat.

**Impact:** Medium. Affects `design_doc.md`, `data/knowledge_base/profile.yaml`, `assembler/static_ingestor.py`, and `assembler/yaml_builder.py`.

---

## ADR-019: Expand Structured Header with `date` and `summary`

**Status:** `[PENDING]`

**Context:** The structured header in experience/project markdown files lacks a `date` field (for custom formatting) and a `summary` field (for role description).

**Decision:** Add `date TEXT` and `summary TEXT` to the `knowledge_sources` table. `date` is a free-form string that maps directly to RenderCV's `date` field, giving the user control over formatting (e.g., "Jan 2022 – Present"). `summary` maps to RenderCV's `summary` field under each experience entry.

**Rationale:** `start_date`/`end_date` are machine-readable but rigid. A custom `date` string is essential for resumes. `summary` lets users write a per-experience blurb in the context paragraph, separate from individual ## stories.

**Impact:** Low. Affects `storage/db.py`, `knowledge_base/parser.py`, and `assembler/yaml_builder.py`.

---

## ADR-020: Validation Rules in Dedicated File with Two Layers

**Status:** `[PENDING]`

**Context:** Validation rules are currently implicit in `generator/validator.py`. There is no separation between "what is checked" and "how it is orchestrated." Additionally, there is no validation across multiple CV points (whole-CV level).

**Decision:**
1. Create `generator/validation_rules.py` holding all rule definitions as pure functions. Each rule returns a `RuleResult` dataclass.
2. `generator/validator.py` imports rules and orchestrates them, exposing `validate_point(point) -> ValidationResult` and `validate_cv(points) -> ValidationResult`.
3. **Point-level rules** (run during generation): verb-first, under 200 chars, no pronouns, has_metrics flag.
4. **Whole-CV rules** (run during assembly): duplicate verbs across bullets, minimum skill coverage, consistent past tense.

**Rationale:** Separating rules from orchestration makes rules testable in isolation and version-controllable. Two validation layers catch individual quality issues early and cross-bullet issues before YAML export.

**Impact:** Medium. Affects `generator/validation_rules.py` (new), `generator/validator.py`, `generator/engine.py`, and `assembler/yaml_builder.py`.

---

## ADR-021: Framing Technique Registry (Deferred)

**Status:** `[DEFERRED]`

**Context:** The generator engine currently hard-codes STAR as the input framing. The user wants to benchmark multiple techniques (CAR, SOAR, PAR, FAB) in the future.

**Decision:** Design a `FRAMING_REGISTRY` in `generator/framing.py` mapping technique names to prompt templates, but do not implement it yet. STAR remains the hard-coded default in `generator/engine.py`. Track this in `FUTURE_ROADMAP.md` §1.

**Rationale:** The architecture should acknowledge future extensibility, but implementing a registry before the core pipeline works is premature optimization.

**Impact:** Low. Affects `generator/framing.py` (future) and `generator/engine.py`.

---

## ADR-022: RenderCV Integration via Python API

**Status:** `[PENDING]`

**Context:** The design doc previously stated the system boundary ends at `cv-output.yaml`. The user wants the system to generate the final PDF using RenderCV.

**Decision:**
1. Extend the system boundary to PDF generation. The assembler writes `cv-output.yaml` and then calls RenderCV's Python API to render it.
2. Use `rendercv.schema.rendercv_model_builder.build_rendercv_dictionary_and_model` to validate the YAML, then `rendercv.renderer.typst.generate_typst` and `rendercv.renderer.pdf_png.generate_pdf` to produce the PDF.
3. Do NOT shell out to `rendercv render` CLI. Use the Python API for structured exception handling (`RenderCVUserValidationError`, `RenderCVUserError`).
4. `profile.yaml` serves as the RenderCV base file. The assembler appends dynamic sections (`experience`, `projects`, `skills`) to `cv.sections`.

**Rationale:**
- Python API gives us structured exceptions with YAML line numbers, which is critical for debugging generated YAML.
- No subprocess overhead or shell escaping issues.
- The pipeline is still fully inspectable: we build a dict, dump YAML, validate with RenderCV's Pydantic models, then call named renderer functions.
- `profile.yaml` doubles as the RenderCV base file, reducing file sprawl.

**Alternative considered:** Shell out to CLI. Rejected because subprocess error handling is coarse and the user can't see which YAML line caused validation failures.

**Impact:** High. Affects `design_doc.md`, `pyproject.toml`, `data/knowledge_base/profile.yaml`, `assembler/yaml_builder.py`, `assembler/rendercv_integration.py`.

---

## ADR-023: Multi-Point Detection in Draft-First Flow (Deferred)

**Status:** `[DEFERRED]`

**Context:** A single `##` chunk may contain multiple distinct achievements. The user can split it manually or use `### ACHIEVEMENT` sub-delimiters, but the system does not proactively suggest splitting.

**Decision:**
1. **Default:** One `##` section → one CV point. The parser and generator enforce this.
2. **Escape hatch 1:** User manually splits the `##` into multiple `##` sections.
3. **Escape hatch 2:** User adds `### ACHIEVEMENT` markers within a `##` section. The parser subdivides.
4. **Future (deferred):** During the draft-first questioning flow, the system detects rich chunks and asks: *"This chunk seems to have N distinct achievements. Generate N points?"* If the user agrees, the generator runs N focused sub-prompts on the same chunk text.

**Rationale:**
- Auto-detection requires a classifier (LLM call or heuristic) that adds latency and complexity.
- Manual splitting and `### ACHIEVEMENT` are explicit, inspectable, and teach the user good chunking habits.
- The deferred "split this" prompt is a natural extension of the questioning flow and can be A/B tested once benchmark fixtures exist.

**Impact:** Medium. Affects `generator/engine.py`, `generator/prompts.py`, `knowledge_base/parser.py`, and `cli/interface.py`.

---

## ADR-024: One File Per Company with Stacked Role Entries

**Status:** `[PENDING]`

**Context:** A user may be promoted or change titles while staying at the same company. RenderCV does not natively support multiple positions within one `ExperienceEntry`, so the presentation layer cannot show a single company block with nested roles.

**Decision:**
1. **One file per company, always.** Even if the user held 3 titles at the same company, they maintain a single Story Portfolio file.
2. Use the `roles` array in YAML frontmatter: a list of `{title, start_date, end_date}` objects.
3. Add `_Role_: <title>` as an optional metadata hint on stories. Stories without this tag default to the most recent role.
4. The assembler groups approved `CVPoint` objects by role and emits N `ExperienceEntry` objects for the same company. RenderCV renders them as stacked entries.

**Open sub-decision:** Whether stacked entries (separate blocks) or a single block (latest title only) looks better in the final PDF is deferred until we can see actual RenderCV output. The assembler can switch between these modes without changing the knowledge base schema. Tracked in `FUTURE_ROADMAP.md` §9.

**Rationale:**
- **Narrative continuity:** Company culture, product domain, relationships, and team dynamics are shared across roles. Splitting into multiple files forces context duplication and breaks the story of growth.
- **Authoring simplicity:** The user thinks "my time at Acme Corp," not "my Senior Engineer file and my Staff Engineer file."
- **Presentation-layer concern:** The knowledge base should not be constrained by RenderCV's schema limitations. The assembler adapts the data to the format.
- **Recruiter signal:** Stacked entries clearly show career progression, which is a strong positive signal.

**Alternative considered:** Split into multiple files (`01_acme-senior.md`, `02_acme-staff.md`). Rejected because it fragments shared context and complicates the user's mental model.

**Impact:** Medium. Affects `design_doc.md`, `docs/knowledge_base_authoring_guide.md`, `knowledge_base/parser.py`, `assembler/yaml_builder.py`, and `TECH_SPEC.md`.

---

## Implementation Priority Queue

### Must-Do Before First Feature
1. `models/schemas.py` + `models/enums.py` (blocks everything)
2. `config.py` with Pydantic settings (blocks LLM client)
3. `storage/repository.py` with CRUD interface (blocks generator)
4. `llm_client/instructor_wrapper.py` (blocks generator)
5. `generator/validation_rules.py` + `generator/validator.py` (blocks generator pipeline)

### High Value, Can Defer
6. Markdown grammar convention (ADR-004)
7. Embedding matrix cache (ADR-008)
8. Ground-truth benchmark fixtures (ADR-014)
9. Consolidate static info into `profile.yaml` (ADR-018)
10. Expand structured header with `date` and `summary` (ADR-019)

### Polish / Nice-to-Have
11. Domain taxonomy file (ADR-016)
12. `models/__init__.py` re-exports (ADR-010)
13. ~~Remove `has_metrics` boolean if not needed~~ (ADR-015 — done: moved to `CVPoint` computed field)
14. SQLite JSON1 filtering (ADR-017)
15. PyYAML assembler (ADR-009)
16. Click CLI (ADR-011)
17. Test strategy execution (ADR-012)
18. Editable install docs (ADR-013)
19. Prompt versioning (ADR-006)
20. Structured validator feedback (ADR-007)
21. Framing technique registry (ADR-021 — deferred)
