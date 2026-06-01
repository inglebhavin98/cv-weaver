# Knowledge Base Authoring Guide

> **Purpose:** How to write experience and project files so the generator produces the best CV points.
> **Principle:** One file = one experience. Inside, you write stories. Each story becomes one or more CV points after QnA refinement.

---

## 1. File Naming

Format: `01_<descriptive-name>.md`

```
experience/
  01_tata-neu.md
  02_nvidia-research.md
projects/
  01_side-project.md
  02_open-source-lib.md
```

**Rules:**
- Use a **two-digit prefix** (`01`, `02`, … `99`). Zero-padding matters: `02` sorts before `10`.
- The number is for **chronological ordering** only. `01` = oldest, `99` = most recent.
- The rest of the filename is a short, human-readable slug.
- Gaps are fine (`01_`, `03_`).
- Projects use the same naming convention and file format as experience files.

**Why:** The parser scans files in order. Chronological order means the generator sees your career progression the way a recruiter would.

---

## 2. File Structure: One Experience = One File

Each file contains:

1. **YAML Frontmatter** — company, position, date, location, domain tags
2. **Optional Context Paragraph** — high-level summary of the role
3. **Stories** — narrative chunks, each under a `##` heading

```markdown
---
file_id: 01_tata-neu
company: Tata Neu
position: Senior Software Engineer
date: Jan 2022 – Present
location: Mumbai, India
employment_type: Full-time
domain_tags: [fintech, platform, backend]
---

I joined when the platform was a monolith serving 1M users. Over 18 months, I led the backend team of 5 engineers, reporting to the VP of Engineering. We migrated to microservices and established SLOs.

## Payment Orchestration Overhaul

Our payments system was hitting limits during flash sales. Query times spiked to 800ms P95 and we had two outages in Q1. I was responsible for payments reliability.

I designed a circuit-breaker pattern using Redis caching and async workers. I paired with two engineers and shipped incrementally over six weeks.

P95 latency dropped to 120ms. No outages in the following two quarters. The pattern was adopted by two other teams.

_Skills_: Python, Redis, Kubernetes
_Metrics_: P95 latency 800ms → 120ms, $10M daily volume
_Team_: 3 engineers, 6 weeks

## Auth Service Migration to Go

The auth service was a 40k LOC Python monolith with 45-minute deploy times. I owned the migration.

I extracted it to a standalone Go service with gRPC interfaces. Built the deployment pipeline with Helm and Prometheus monitoring.

Throughput increased 3x. Deploy time dropped to 3 minutes. Reduced blast radius — payments stayed up during auth outages.

_Skills_: Go, gRPC, Helm, Prometheus
_Metrics_: 3x throughput, deploy 45min → 3min

## Team Building & Mentoring

I hired 3 backend engineers and built an onboarding checklist. I paired with each new hire for their first month. All were productive within 2 weeks.

_Skills_: Hiring, mentoring, onboarding
_Metrics_: 3 hires, 2-week ramp-up
```

---

## 3. YAML Frontmatter

The header lives between `---` fences. It is parsed as YAML.

| Field | Required? | Used by Pipeline? | Example |
|-------|-----------|-------------------|---------|
| `file_id` | Yes | Yes — DB primary key | `01_tata-neu` (must match filename stem) |
| `company` | Yes | No — reference only | `Tata Neu` |
| `position` | Yes | No — reference only | `Senior Software Engineer` |
| `date` | No | No — reference only | `Jan 2022 – Present` — free-form, shown in the final CV |
| `start_date` | No | No — reference only | `2022-01` — machine-readable, fallback if `date` omitted |
| `end_date` | No | No — reference only | `2024-06` or `present` |
| `location` | No | No — reference only | `Mumbai, India` |
| `employment_type` | No | No — reference only | `Full-time`, `Contract`, `Freelance` |
| `domain_tags` | No | No — future use (Component 4) | `[fintech, platform]` |
| `roles` | No | No — not yet implemented | See §8 Promotions (future feature) |

**Tips:**
- `domain_tags` are stored per-point by the LLM drafter. Frontmatter `domain_tags` is reserved for future use.
- `company` and `position` are human-readable labels for your own reference. They do not flow into generated CV points today.
- All metadata fields are optional with sensible defaults. You will never be blocked from generating a point.
- Use the `roles` array instead of `position` when you held multiple titles at the same company. See Section 8 (not yet implemented).

---

## 4. The Context Paragraph (Optional)

After the frontmatter and before any `##` heading, you can write a few sentences that set the scene:

```markdown
I joined when the platform was a monolith serving 1M users. Over 18 months...
```

**Why this helps:** The parser passes this context to every story in the file. When the LLM generates a point from `## Payment Orchestration`, it knows you were "leading the backend team of 5" — it enriches the point without you repeating it in every story.

---

## 5. Writing Stories

### 5.1 One `##` = One Story

Each `##` heading is a self-contained story. The parser treats it as an independent unit for generation.

**What a story contains:**
- **2–5 paragraphs** of narrative text
- **Optional metadata hints** at the bottom (`_Skills_`, `_Metrics_`, `_Team_`)

You do **not** need to format the story as STAR. Write it naturally. The LLM extracts STAR from the narrative flow.

### 5.2 What to Write in a Story

A good story answers these implicitly:

| Element | What to include | Why it helps |
|---------|----------------|--------------|
| **Situation/Problem** | What was broken, slow, missing, risky? | Gives the LLM context for impact |
| **Your role** | What were you specifically responsible for? | Clarifies scope vs. team effort |
| **Action** | What did you build/design/write/lead? | Becomes the action verb + context |
| **Result** | Numbers, percentages, time saved, money made? | Becomes metrics in the bullet |
| **Tools** | Python, Kubernetes, Postgres, etc. | Feeds `skills_utilized` |
| **Scope** | Team size, users affected, systems involved | Adds credibility and scale |

You don't need all of these. Write what you remember. The QnA loop will ask for what's missing.

### 5.3 Good Story Example

```markdown
## Payment Orchestration Overhaul

Our payments system was hitting limits during flash sales. Query times spiked to 800ms P95 and we had two outages in Q1. I was responsible for payments reliability.

I designed a circuit-breaker pattern using Redis caching and async workers. I paired with two engineers and shipped incrementally over six weeks.

P95 latency dropped to 120ms. No outages in the following two quarters. The pattern was adopted by two other teams.

_Skills_: Python, Redis, Kubernetes
_Metrics_: P95 latency 800ms → 120ms, $10M daily volume
_Team_: 3 engineers, 6 weeks
```

**Why this is good:**
- Paragraph 1: Situation (spikes, outages, your role)
- Paragraph 2: Action (designed, paired, shipped)
- Paragraph 3: Result (latency drop, no outages, adoption)
- Metadata: hints that the LLM uses or validates against

### 5.4 Metadata Hints Are Optional

Metadata lines start with an underscore and end with a colon. They are **hints**, not requirements.

```markdown
_Skills_: Python, Redis, Kubernetes
_Metrics_: P95 latency 800ms → 120ms
_Team_: 3 engineers, 6 weeks
_Role_: Senior Software Engineer
```

| Hint | Purpose | If omitted |
|------|---------|------------|
| `_Skills_` | Technologies you used | LLM infers from narrative or asks in QnA |
| `_Metrics_` | Quantifiable outcomes | LLM asks "Can you quantify this?" in QnA. Point is still generated. |
| `_Team_` | Team size, reporting structure | LLM infers or asks |
| `_Role_` | Which role this story belongs to | Optional; used for promotions (see §8) |

**You will never be blocked** from generating a point because you forgot a metadata line.

---

## 6. Projects vs. Experience

Projects follow the **exact same format** as experience files. Put them in `projects/` instead of `experience/`.

```markdown
---
file_id: 01_resume-builder-ai
company: Personal Project
position: Author
date: Jan 2024 – Present
---

## AI-Powered Resume Builder

I built a CLI tool that generates structured CV points from raw work-history markdown using local LLMs...
```

The pipeline treats projects identically — they generate `CVPoint` objects with `experience_type="project"`. The only difference is semantic: project stories often emphasize technical depth and independent execution over team scale.

---

## 7. Handling Different Story Types

Not every story is a standalone achievement. That's fine — the LLM adapts.

### Achievement Story (default)

One-time impactful work. Generates a strong CV point.

```markdown
## Payment Orchestration Overhaul

...designed circuit-breaker, latency dropped 85%...
```

### Responsibility Story

Ongoing ownership. Generates a "Managed/Led/Owned" point.

```markdown
## Backend Platform Team Lead

I was the tech lead for the backend platform team. I ran sprint planning, reviewed architecture decisions, and managed stakeholder communication with product and SRE. The team maintained 12 microservices with 99.97% uptime.

_Skills_: Leadership, architecture review, stakeholder management
_Team_: 5 engineers
```

### Context Story

Team growth, hiring, process — things that don't shine alone but enrich other points.

```markdown
## Hiring & Onboarding

I hired 3 backend engineers and built an onboarding checklist. I paired with each new hire for their first month. All were productive within 2 weeks.

_Skills_: Hiring, mentoring
_Metrics_: 3 hires, 2-week ramp-up
```

This might become a standalone point: *"Hired and onboarded 3 engineers, achieving 2-week productivity ramp-up."* Or it might merge into a sibling responsibility story.

### Skill-Deepening Story

You learned a technology deeply.

```markdown
## Kubernetes Migration

Our deploy pipeline was manual and error-prone. I spent three months learning Kubernetes and Helm deeply, then migrated our entire staging environment. I documented the process and gave two internal tech talks.

_Skills_: Kubernetes, Helm, technical writing
```

Generates: *"Migrated staging environment to Kubernetes and Helm, reducing deploy errors and delivering internal documentation + 2 tech talks."*

---

## 8. Promotions and Role Changes (Same Company) — *Future Feature*

> **Status:** Not yet implemented. The parser accepts the `roles` array and `_Role_` hints, but the generator and assembler do not use them today.
> 
> This section documents the intended design for when Component 5 (YAML Assembler) is built.

If you were promoted or changed titles while staying at the same company, **keep one file**.

Use the `roles` array in the YAML frontmatter and tag stories with `_Role_`:

```yaml
---
file_id: 01_acme-corp
company: Acme Corp
domain_tags: [fintech, backend]
roles:
  - title: Staff Engineer
    start_date: 2024-03
    end_date: present
  - title: Senior Engineer
    start_date: 2021-06
    end_date: 2024-03
---

I joined as a Senior Engineer and was promoted to Staff after leading the platform migration.

## Payment Orchestration Overhaul

I redesigned the payments circuit-breaker...

_Skills_: Python, Redis
_Metrics_: P95 latency 800ms → 120ms
_Role_: Senior Engineer

## Platform Team Leadership

As a Staff Engineer, I led the platform team of 8...

_Skills_: Leadership, Architecture
_Metrics_: Team grew from 3 to 8
_Role_: Staff Engineer
```

**Rules (when implemented):**
- Stories **without** a `_Role_` tag are attributed to the most recent role.
- The assembler groups points by role and emits stacked entries in the final CV.
- Do **not** split into multiple files for the same company — the shared context and narrative continuity are valuable.

**Why one file:** Company culture, product domain, relationships, and team dynamics are shared across roles. Splitting into multiple files forces you to duplicate context and breaks the narrative of your growth.

---

## 9. What If You Don't Have Metrics?

Write the story anyway. The QnA loop will ask, but won't block.

```markdown
## Checkout Flow Redesign

The checkout had a 60% drop-off rate. I redesigned it with clearer progress indicators and error handling. The product manager was happy with the result.

_Skills_: React, UX design
```

**QnA:** *"Can you quantify the drop-off improvement?"*

- **User:** "Went from 60% to 35% drop-off" → point updated
- **User:** "Don't have numbers" → point kept with `has_metrics = False`

Both paths are valid. The point exists in the pool. You decide later whether to include it in the final CV.

---

## 10. Common Mistakes

| Mistake | Why It Hurts | Fix |
|---------|-------------|-----|
| One `##` with 5 unrelated paragraphs | LLM extracts confused points | Split into separate `##` stories |
| No paragraphs — just bullet list | LLM loses narrative context | Write 2–3 paragraphs of prose |
| Vague action verbs in the story | LLM can't find a strong verb | Be specific: "designed", "implemented", "refactored" |
| Forgetting `##` headers | Parser can't find stories | Every story starts with `##` |
| Over-polishing the narrative | You write CV-ready bullets, not raw stories | Write the story, let the system polish it |

---

## 11. Complete Example

```markdown
---
file_id: 02_nvidia-research
company: NVIDIA Research
position: Research Intern
date: May 2022 – Aug 2022
location: Santa Clara, CA
employment_type: Internship
domain_tags: [ml, systems, research]
---

I spent the summer in the ML Systems group working on efficient transformer inference. My mentor was a senior researcher focused on edge deployment.

## Sparse Attention Mechanism

Transformers were hitting memory limits on long sequences. Standard attention is O(n²) in memory. I was asked to explore sparser patterns.

I designed an attention mechanism that skips distant token pairs. Implemented it in CUDA and integrated it into the team's PyTorch training pipeline.

Reduced memory footprint by 4.2x on a 4096-token benchmark. The work became a NeurIPS 2022 spotlight paper (top 5%).

_Skills_: PyTorch, CUDA, transformer architectures
_Metrics_: 4.2x memory reduction, NeurIPS spotlight

## Quantization Pipeline for Edge Deployment

Model sizes were too big for Jetson Nano deployment. The team needed an automated way to apply INT8 quantization without significant accuracy loss.

I built a pipeline that applies INT8 quantization with per-channel scaling. I ran experiments across 10 model architectures.

2.3x speedup on Jetson Nano. Accuracy drop was only 0.4% on ImageNet. The pipeline was adopted by the edge inference team.

_Skills_: PyTorch, ONNX Runtime, TensorRT, INT8 quantization
_Metrics_: 2.3x speedup, 0.4% accuracy drop
```

---

## 12. Quick Reference

```
experience/          or          projects/
  01_file_name.md                 01_file_name.md
    ├── YAML Frontmatter
    │     file_id (required)
    │     company, position (reference only)
    │     date, location, employment_type (optional)
    │
    ├── Context Paragraph (optional)
    │     High-level role summary
    │
    └── Stories
          ├── ## Story Title
          │     Paragraph 1: situation / problem
          │     Paragraph 2: what you did
          │     Paragraph 3: result / outcome
          │     _Skills_: tool, tool, tool
          │     _Metrics_: number, number
          │     _Team_: size, duration
          │     _Role_: role title (optional)
          │
          ├── ## Another Story
          │     ...
          │
          └── ## A Third Story
                ...
```

---

> **Bottom line:** One file = one experience or project. Write stories, not bullets. Include numbers where you have them. The system asks for what's missing. Every story is a candidate for a CV point — the QnA loop decides how many and how good.
> 
> **Currently supported:** `file_id` (required), `_Skills_`, `_Metrics_`, `_Team_`, `_Role_` hints, `##` story headings.
> **Not yet supported:** `roles` array (promotions), frontmatter `domain_tags` (reserved for Component 4).
