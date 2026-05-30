
> **Purpose:** Learning AI engineering by building a utility resume generation system. 
> **Status:** Feature design locked. Ready for AI engineering layer.

---

## Table of Contents

1. [System Goal](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#1-system-goal)
2. [High-Level Data Flow](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#2-high-level-data-flow)
3. [Component 1 — Knowledge Base Structure](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#3-component-1--knowledge-base-structure)
4. [Component 2 — CV Points Generator Engine](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#4-component-2--cv-points-generator-engine)
5. [Component 3 — Storage & Management](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#5-component-3--storage--management)
6. [Component 4 — Customizer Engine](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#6-component-4--customizer-engine)
7. [Component 5 — Selection & Final Generation](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#7-component-5--selection--final-generation)
8. [Canonical CV Point Schema](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#8-canonical-cv-point-schema)
9. [Static Info — Three Tiers](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#9-static-info--three-tiers)
10. [RenderCV YAML Mapping](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#10-rendercv-yaml-mapping)
11. [Full System Architecture (Locked)](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#11-full-system-architecture-locked)

---

## 1. System Goal

**Primary goal:** Learn AI engineering concepts by building real systems.

**Secondary goal (by-product):** A working resume generation system that:

- Maintains a personal knowledge base of work experiences and accomplishments
- Generates high-quality, ATS-optimized CV points
- Customizes resumes for specific domains or job descriptions
- Produces a RenderCV-compatible YAML file and renders it to PDF

> RenderCV handles all formatting, typography, and PDF compilation. The system's job is content generation and assembly; RenderCV is the rendering engine.

---

## 2. High-Level Data Flow

```
Knowledge Base → Generator Engine → CV Points Pool → Customizer Engine → YAML Assembler → RenderCV → cv-output.pdf
```

Every CV point is traceable back to a source experience file. Traceability is the spine of the entire system.

---

## 3. Component 1 — Knowledge Base Structure

### Folder Layout

```
/master
├── profile.yaml                  ← Tier 1 static (personal info + semi-static sections)
├── experience/
│   ├── 01_tata-neu.md            ← oldest experience (structured header + append-only dump)
│   ├── 02_nvidia-research.md     ← newer experience
│   └── 03_nexus-ai.md            ← most recent
└── projects/
    ├── 01_flashinfer.md
    └── 02_neuralprune.md
```

### File Naming Convention

Files in `experience/` and `projects/` use a **two-digit numeric prefix** to enforce chronological order:

```
01_<descriptive-name>.md   ← oldest
02_<descriptive-name>.md   ← newer
03_<descriptive-name>.md   ← most recent
```

**Why:**
- **Deterministic ordering:** File systems sort alphabetically. `01_`, `02_`, `03_` guarantees the parser and the user see experiences in chronological order.
- **Simple and explicit:** No hidden metadata, no frontmatter dates required for ordering. The number is the order.
- **Human-readable:** You can tell at a glance which experience came first.

**Rules:**
- The number is zero-padded to two digits (`01`, `02`, … `99`).
- Gaps are allowed (`01_`, `03_`).
- The prefix is **not** part of the semantic `file_id` unless you choose to include it. The `file_id` is the filename stem (`01_tata-neu`).

### Experience / Project File Structure

Each file is a **Story Portfolio** — a collection of narrative stories about one experience.

```markdown
---
file_id: 01_tata-neu
company: Tata Neu
position: Senior Software Engineer
date: Jan 2022 – Present
---

I joined when the platform was a monolith serving 1M users. Over 18 months...

## Payment Orchestration Overhaul

Our payments system was hitting limits during flash sales...

I designed a circuit-breaker pattern...

P95 latency dropped to 120ms...

_Skills_: Python, Redis, Kubernetes
_Metrics_: P95 latency 800ms → 120ms
_Team_: 3 engineers, 6 weeks
```

**Parts of the file:**

| Part | Description |
|------|-------------|
| **YAML Frontmatter** | Company, position/roles, date, location, domain tags |
| **Context Paragraph** *(optional)* | High-level role summary. Enriches all stories in the file |
| **`## Stories`** | Narrative chunks, each under a `##` heading. 2–5 paragraphs + optional metadata hints |

**Metadata hints** (all optional, placed at the end of a story):

| Hint | Purpose |
|------|---------|
| `_Skills_` | Technologies used. Populates `skills_utilized` |
| `_Metrics_` | Quantifiable outcomes. Populates `impact_metrics` |
| `_Team_` | Team size, reporting structure. Adds scope to the point |
| `_Role_` | Which role this story belongs to. Used for promotions (see below) |

The narrative is written naturally — not as STAR, not as bullets. The LLM extracts STAR from the story. Metadata hints are optional suggestions the LLM uses or validates against.

### Promotions Within the Same Company

One file per company, even if you held multiple titles. Use the `roles` array in YAML frontmatter (list of `{title, start_date, end_date}`) and tag stories with `_Role_: <title>`. The assembler groups points by role and emits stacked entries in the final CV. Stories without a `_Role_` tag default to the most recent role.

See `docs/knowledge_base_authoring_guide.md` §11 for a complete example.

---

## 4. Component 2 — CV Points Generator Engine

### Responsibilities

- Parses experience files into stories (narrative chunks under `##` headings)
- Runs a **two-level generation pipeline**: per-story extraction → experience-level refinement
- Presents drafts to the user and drives QnA refinement
- Validates and stores approved points

### Two-Level Generation Pipeline

**Level 1: Per-Story Extraction**

Each `##` story is fed to the LLM as a narrative + optional metadata hints. The LLM extracts STAR components and produces **candidate CV points**.

```
Story (narrative + metadata) → LLM → CVPointCandidate(s)
```

- The LLM decides how many distinct points the story contains (typically 1–2, up to 3)
- The story's metadata hints (`_Skills_`, `_Metrics_`) are used or validated against
- The experience file's context paragraph is injected as background

**Level 2: Experience-Level Refinement**

After all stories in one experience file are processed, the system runs refinement across all candidate points from that experience:

```
All CVPointCandidates → Refinement Engine → Refined Experience Points
```

| Operation | Description |
|-----------|-------------|
| **Merge duplicates** | Two candidates with same verb + similar context → keep the stronger one |
| **Split rich points** | One candidate with 2+ distinct achievements → ask user: "Split into 2 points?" |
| **Drop weak points** | No clear contribution, vague scope → flagged for user review |
| **Re-order** | Sort by estimated impact score |
| **Coverage check** | Skills from metadata not reflected in any point → flag gap |

The user reviews the refined set (typically 5–8 points per experience) and approves, edits, or drops each one.

### QnA Refinement (Per-Story)

After Level 1 generates candidates, the system asks targeted questions **per story** before the user reaches Level 2:

| Draft Problem | Question Asked |
|---------------|----------------|
| No metrics in `rendered_bullet` | "Can you quantify the result? E.g., percentage, dollar amount, time saved?" |
| Weak action verb | "What was the single most impactful thing you *built* or *designed*?" |
| Unclear scope | "How many people/systems were affected?" |
| Missing skills | "What tools or technologies did you use?" |
| Pronouns found | "Remove 'I' — rephrase as 'Led team of 3 to...'" |
| Rich story (2+ achievements) | "This story seems to have 2 distinct accomplishments. Split into 2 points?" |

The user answers → LLM regenerates → re-validate. Typically 2–3 QnA rounds per story.

**Metrics are optional.** If the user has no numbers, the system stores the point with `has_metrics = False`. The point still enters the pool — the user decides later whether to include it in the final CV.

### Validation Rules

Before a candidate is stored, it must pass point-level validation:

1. `rendered_bullet` starts with `components.action_verb`
2. Length under 200 characters
3. No pronouns (I, me, my, we, our)
4. If `impact_metrics` is empty → flag for metric suggestion (non-blocking)

After Level 2 refinement, whole-CV validation runs (duplicate verbs, skill coverage, tense consistency).

---

## 5. Component 3 — Storage & Management

### Storage Strategy

- **Input:** Markdown files (human-readable, version-controllable)
- **Processing & querying:** Structured database (SQLite or equivalent)
- **Export:** Markdown (for human review if needed)
- The DB is the source of truth; markdown is for readability and editing

### Redundancy Handling

- The system **flags** redundant points (two points describing the same achievement)
- User can review flagged pairs and choose to keep, discard, or **auto-merge**
- Auto-merge option available but not forced

### What Each CV Point Stores

See [Section 8 — Canonical CV Point Schema](https://claude.ai/chat/5c6107a7-aaa7-4fde-9267-b4c2323d0530#8-canonical-cv-point-schema) for the full schema.

Key management metadata per point:

- Score and ranking fields
- Domain tags and classification
- Status: `draft`, `approved`, `archived`
- Redundancy flag
- Derivation chain (parent point ID)

---

## 6. Component 4 — Customizer Engine

### Two Modes

**Mode A — Domain-based**

- Input: target domain (e.g., "fintech", "backend engineering")
- Adapts existing CV points to domain-specific language, keywords, and framing
- Useful for generating a general domain-targeted resume

**Mode B — JD-based**

- Input: a specific job description
- Matches existing CV points to JD requirements
- Rewrites points using the JD's language, skills, and terminology
- Tags output points as `jd-specific`

### Logic Flow

1. First, try to **adapt existing approved points** from the pool
2. If coverage gap is too large, **fall back to generating fresh points** from the raw dump
3. Fresh points generated for a JD are tagged as `jd-specific` and tracked separately — they do not pollute the general pool

---

## 7. Component 5 — Selection & Final Generation

### Web UI (Simple)

- Filter CV points by: domain, score, tags, source experience
- Select points per resume section
- Inline edit selected points before export
- Skills section **auto-derived** from `skills_utilized` metadata of selected points
- Tier 2 static sections (education, publications, patents, talks, honors) included as-is

### Final Action

The user hits **Export PDF** → the YAML assembler produces `cv-output.yaml` → calls RenderCV programmatically → produces `cv-output.pdf`.

---

## 8. Canonical CV Point Schema

```json
{
  "id": "string",
  "created_at": "datetime",
  "updated_at": "datetime",

  "source": {
    "file_id": "01_tata-neu",
    "experience_type": "experience | project | education",
    "raw_dump_excerpt": "the specific lines from the dump this was derived from"
  },

  "extended_context": {
    "situation": "what was the business or technical problem",
    "task": "what was your specific responsibility"
  },

  "components": {
    "action_verb": "single past-tense high-impact verb",
    "context": "scope, problem, or technology stack handled",
    "result": "quantifiable business outcome or technical improvement"
  },

  "rendered_bullet": "Final one-liner CV point starting with action_verb",

  "metadata": {
    "impact_metrics": ["numbers, percentages, or dollar amounts"],
    "skills_utilized": ["tools, technologies, methodologies"]
  },

  "classification": {
    "type": "general | domain-specific | jd-specific",
    "domain_tags": ["fintech", "backend"],
    "target_jd_id": "null unless jd-specific",
    "status": "draft | approved | archived",
    "parent_point_id": "ID of the point this was derived from, if any"
  },

  "scores": {
    "impact_score": "0–10",
    "ats_score": "0–10",
    "completeness_score": "0–10"
  },

  "has_metrics": "true | false    ← derived: len(impact_metrics) > 0"
}
```

### Derivation Chain

Points can be derived from each other, forming a traceable tree:

```
[General Point]  ──derives──▶  [Domain Point]  ──derives──▶  [JD-Specific Point]
       │                              │                               │
 01_tata-neu                  "fintech" tag                  "Zepto JD – July 2025"
```

---

## 9. Static Info — Two Tiers

|Tier|Contents|Storage|Changes|
|---|---|---|---|
|**Tier 1 — Profile Config**|name, email, phone, LinkedIn, website, location, education, publications, patents, invited talks, honors|`profile.yaml`|Personal info rarely (once a year); semi-static sections grow over time|
|**Tier 2 — Dynamic**|experience CV points, project CV points|Goes through full generator → CV Points Pool|Continuously generated and customized|

Tier 1 now holds **both** personal info and semi-static sections (education, publications, etc.). This keeps the knowledge base flatter and reduces file sprawl. These sections are included in the final YAML as-is without going through the generator or customizer engine.

---

## 10. RenderCV YAML Mapping

|RenderCV YAML Field|Source in This System|
|---|---|
|`cv.name`, `email`, `phone`, etc.|`profile.yaml` → `cv` block|
|`cv.headline`|Manually written or generated per CV|
|`cv.sections.experience[].highlights[]`|Selected `rendered_bullet` values from CV Points Pool|
|`cv.sections.experience[].date`|`knowledge_sources.date` (or `start_date`/`end_date` fallback)|
|`cv.sections.experience[].summary`|`knowledge_sources.summary` (optional)|
|`cv.sections.experience[]` (stacked)|Same company, multiple roles → N entries grouped by `_Role_` tag|
|`cv.sections.projects[].highlights[]`|Selected `rendered_bullet` values (project-type points)|
|`cv.sections.skills[].details`|Auto-aggregated from `skills_utilized` of selected points|
|`cv.sections.education`|`profile.yaml` → `cv.sections.education`|
|`cv.sections.publications`|`profile.yaml` → `cv.sections.publications`|
|`cv.sections.patents`|`profile.yaml` → `cv.sections.patents`|
|`cv.sections.invited_talks`|`profile.yaml` → `cv.sections.invited_talks`|
|`cv.sections.selected_honors`|`profile.yaml` → `cv.sections.honors`|
|`design.theme`|`profile.yaml` → `design.theme` (optional)|

---

## 11. Full System Architecture (Locked)

```
┌─────────────────────────────────────────────────────────────────┐
│  KNOWLEDGE BASE                                                 │
│                                                                 │
│  profile.yaml           ← Tier 1: personal info + semi-static  │
│  experience/01_*.md     ← Story Portfolio (YAML + ## stories)  │
│  projects/01_*.md                                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ read by
┌──────────────────────────▼──────────────────────────────────────┐
│  GENERATOR ENGINE                                               │
│                                                                 │
│  Level 1 — Per-Story Extraction                                 │
│    Parse ## stories → narrative + metadata hints                │
│    LLM extracts STAR → CVPointCandidate(s) per story            │
│    Point-level validation + QnA refinement loop                 │
│                                                                 │
│  Level 2 — Experience-Level Refinement                          │
│    Merge duplicates, split rich points, drop weak               │
│    Re-order by impact, flag coverage gaps                       │
│    User reviews refined set (~5–8 points per experience)        │
│                                                                 │
│  Produces canonical CVPoint objects → store in pool             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ stores into
┌──────────────────────────▼──────────────────────────────────────┐
│  CV POINTS POOL  (DB + MD export)                               │
│                                                                 │
│  - Full canonical schema per point                              │
│  - Scored, tagged, domain-labelled                              │
│  - Source traceable to knowledge base story                     │
│  - Derivation chain: general → domain → jd-specific            │
│  - Redundancy flagged (with auto-merge option)                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ fed into
┌──────────────────────────▼──────────────────────────────────────┐
│  CUSTOMIZER ENGINE                                              │
│                                                                 │
│  Mode A — Domain:  adapt existing points to domain language     │
│  Mode B — JD:      match + rewrite for specific job description │
│  Fallback:         generate fresh from stories if coverage gap  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ user selects via
┌──────────────────────────▼──────────────────────────────────────┐
│  WEB UI  (simple)                                               │
│                                                                 │
│  - Filter by domain, score, tags                                │
│  - Select points per section                                    │
│  - Inline edit before export                                    │
│  - Skills section auto-derived from selected points             │
│  - Semi-static sections from profile.yaml included as-is        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ assembles
┌──────────────────────────▼──────────────────────────────────────┐
│  YAML ASSEMBLER + RENDERCV INTEGRATION                          │
│                                                                 │
│  profile.yaml           → base YAML (personal info + static)   │
│  selected CVPoints      → highlights[] per section              │
│  knowledge_sources      → date, summary per experience entry    │
│  skills_utilized        → skills section (aggregated)           │
│                                                                 │
│  Whole-CV validation: verb diversity, skill coverage, tense     │
│  RenderCV Python API    → YAML → Typst → PDF                    │
│                                                                 │
│  OUTPUT: cv-output.pdf    ◀── system boundary ends here       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Next Step

Feature design is locked. The next phase is mapping AI engineering concepts onto each component:

- RAG for reading and querying the knowledge base
- Structured outputs / tool use for canonical schema enforcement
- LLM-as-judge for benchmarking CV point quality
- Embeddings for redundancy detection
- Prompt architecture for the generator and customizer engines