# cv-weaver Future Roadmap

> **Status:** Not in current scope. Tracked for future experimentation and benchmarking.
> **Purpose:** Keep the design doc and tech spec clean by parking out-of-scope ideas here.

---

## 1. Generator Framing Techniques

**Current:** STAR (Situation, Task, Action, Result) is the only framing technique used for the generator engine input.

**Future:** Support and benchmark multiple framing techniques to see what produces the best CV points.

| Technique | Description | When to Test |
|-----------|-------------|--------------|
| **STAR** (current) | Situation → Task → Action → Result | Baseline. Good for structured, metric-heavy achievements. |
| **CAR** | Challenge → Action → Result | Simpler than STAR. Good when the "Task" is identical to the "Action." |
| **SOAR** | Situation → Obstacle → Action → Result | Emphasizes overcoming difficulty. Good for turnaround or rescue stories. |
| **PAR** | Problem → Action → Result | Minimal framing. Good when the situation is obvious from context. |
| **FAB** | Feature → Advantage → Benefit | Product-oriented. Good for project descriptions where the *outcome* is the selling point. |

**Implementation idea:** A `FRAMING_REGISTRY` dict in `generator/framing.py` mapping technique names to prompt templates. The benchmark harness runs the same raw dump through each technique and compares output quality.

---

## 2. Formal Questioning Document

**Current:** The questioning flow is embedded in `generator/engine.py` as ad-hoc clarifying questions (missing metrics, scope clarification, impact specificity).

**Future:** A standalone `docs/questioning_framework.md` spec that defines:
- Question taxonomy (metric, scope, impact, skill, verb)
- When each question is triggered (conditional rules)
- Expected answer format (free text, number, pick-list)
- How answers are merged back into the point components

**Why defer:** The current 3-question flow is sufficient for learning. A formal framework is over-engineering until the system has 20+ real CV points and the question patterns stabilize.

---

## 3. Output Format Variants

**Current:** All points are rendered as `action_verb + context + result` one-liners (max 200 chars, no pronouns).

**Future:** Support multiple output formats for the same underlying `PointComponents`.

| Variant | Style | Use Case |
|---------|-------|----------|
| **Concise** (current) | One-liner, max 200 chars | Dense resumes, ATS optimization |
| **Impact-first** | Lead with metric, then action | Emphasizing quantifiable outcomes |
| **Technical depth** | Longer bullets with tool names | Technical roles where tool stack matters |
| **Narrative** | 2–3 sentence mini-paragraph | Cover letters or LinkedIn summaries |

**Implementation idea:** A `Renderer` protocol with `render(point, variant) -> str`. The canonical schema stays the same; only the final string changes.

---

## 4. Whole-CV Validator Enhancements

**Current (planned):** Basic whole-CV validation (duplicate verbs, skill coverage minimum, consistent tense).

**Future:**
- **Verb diversity scoring:** Track verb frequency across the full CV. Flag if "Led" appears more than twice.
- **Skill coverage heatmap:** After JD-based customization, report which JD-required skills are covered and which have gaps.
- **Section length balancer:** Ensure no single experience section dominates (>50% of bullets).
- **Redundancy clusters:** Group similar points across *different* source files (e.g., "built API" in two jobs).

---

## 5. Domain Taxonomy & Tag Autocomplete

See ADR-016. A controlled vocabulary in `data/domain_taxonomy.yaml` with autocomplete in the CLI.

---

## 6. Multi-Point Detection in Draft-First Flow

**Current:** One `##` chunk produces one CV point. If the chunk is rich, the user must manually split it or add `### ACHIEVEMENT` markers.

**Future:** The system detects rich chunks during the draft-first flow and offers to generate multiple points.

### How It Would Work

1. **Detection:** After generating the first draft, a lightweight classifier (heuristic or LLM call) checks: *"Does this chunk contain multiple distinct achievements?"*
2. **User choice:** The CLI asks: *"This chunk seems to have 3 distinct achievements. Generate 3 separate points?"*
3. **Sub-prompts:** If the user agrees, the generator runs N focused sub-prompts, each targeting one achievement within the chunk.
4. **Validation:** Each sub-point is validated independently, with its own STAR context derived from the chunk.

### Detection Heuristics (No LLM Needed)

| Signal | Threshold |
|--------|-----------|
| Number of distinct action verbs | > 2 |
| Number of quantifiable metrics | > 2 |
| Presence of `### ACHIEVEMENT` markers | Already handled by parser |
| Chunk length | > 400 characters |
| Number of bullet points | > 3 |

A simple rule-based classifier could flag 80% of rich chunks without an LLM call. An LLM-based classifier could be added later for higher precision.

### When to Implement

- After the core pipeline (parser → generator → storage → assembler) is working end-to-end.
- After benchmark fixtures exist (ADR-014) so we can measure whether multi-point detection improves point quality.

---

## 7. In-Context RAG Experiments

**Current:** We use embeddings for *selection* (finding the best points for a JD via cosine similarity), not for *prompt augmentation* (feeding retrieved points into the LLM prompt).

**Future:** A/B test whether retrieving approved points and injecting them into prompts improves quality.

### Why Deferred

1. **The raw dump is already the "retrieved context"** for the generator. Adding old CV points risks recycling phrasing instead of extracting fresh accomplishments.
2. **The customizer rewrites one point against a JD**, not against examples. Few-shot style transfer might lose the point's specific details.
3. **Schema enforcement (Instructor + Pydantic) is a harder constraint than few-shot examples.** Examples add noise — the LLM may mimic structure instead of following the schema.
4. **Token budget:** 5 retrieved points ≈ 1000+ tokens of context. For a per-chunk LLM call, this multiplies latency and cost for marginal gain.
5. **Feedback loop risk:** Poorly approved early points could contaminate later generations if used as examples.

### Where It Could Add Value

| Use Case | How It Would Work | Condition to Test |
|----------|-------------------|-------------------|
| **Customizer rewrite** | Retrieve 2-3 domain-specific points as style examples in the rewrite prompt | After benchmark fixtures exist (ADR-014) |
| **Generator cold-start** | New experience file with no nearby approved pool; retrieved examples from similar domains bootstrap quality | If schema adherence < 90% on new files |
| **Metric prompting** | Retrieve high-impact-score points as examples when validator flags missing metrics | If metric prompting acceptance rate is low |

### Hypotheses to Validate

| Hypothesis | Metric | Threshold |
|------------|--------|-----------|
| Customizer + retrieved domain examples improves ATS score | `ats_score` delta | +1.0 on average |
| Generator + few-shot examples improves schema adherence | Schema pass rate | +5% |
| Metric prompting + examples increases metric acceptance | User accepts metric suggestion | +20% |
| No significant style drift | Redundancy pair count | No increase |

### Implementation Idea

Add a `retriever` parameter to `generator/engine.py` and `customizer/engine.py`:

```python
def generate_draft(
    chunk: str,
    response_model: type[BaseModel],
    retriever: Retriever | None = None,  # NEW
) -> CVPoint:
    prompt = build_prompt(chunk)
    if retriever:
        examples = retriever.retrieve(chunk, k=3)
        prompt += format_examples(examples)
    return llm_client.chat_completion(prompt, response_model)
```

A `Retriever` protocol with two implementations:
- `NullRetriever` (current behavior, no overhead)
- `EmbeddingRetriever` (finds similar approved points via cosine similarity)

The benchmark harness runs each configuration (with vs. without retriever) across the test set.

---

## 8. Explicit STAR Template Option

**Current:** Stories are written as free-form narrative paragraphs. The LLM extracts STAR components from the prose.

**Future:** If benchmark data shows narrative extraction hurts quality (schema adherence < 90%, metric recall < 70%), offer an **explicit STAR template** as an alternative input format.

```markdown
## Payment Orchestration

**Situation:** Our platform was processing $10M daily through a single Postgres instance...
**Task:** I was responsible for reducing payment latency...
**Action:** I designed a circuit-breaker pattern...
**Result:** P95 latency dropped from 800ms to 120ms...

_Skills_: Python, Redis, Kubernetes
_Metrics_: P95 latency 800ms → 120ms
```

**Tradeoffs:**

| Narrative (current) | Explicit STAR (future option) |
|---------------------|--------------------------------|
| Natural to write | Bureaucratic, feels like a form |
| LLM extracts STAR | Machine-parsable, no extraction needed |
| Flexible story structure | Rigid format, users may resist |
| Good for diverse writing styles | Good for users who want structure |

**Decision rule:** Implement only if benchmarks prove narrative extraction is a bottleneck. Default stays narrative. The explicit-STAR template becomes an opt-in format in the authoring guide.

---

## 9. Open Design Questions

### Promotion Rendering: Separate Blocks vs. Single Block?

**Current decision (§7 of Knowledge Base Authoring Guide):** One file per company, `roles` array in frontmatter, `_Role_` tags on stories. Assembler emits stacked entries (same company repeated with different titles).

**Open question:** Does the final PDF look better with:
1. **Separate blocks** — Acme Corp listed twice (Senior, then Staff). Shows clear progression.
2. **Single block** — Latest title only, with a "Promoted to Staff" bullet.

**Status:** Deferred until we can see actual RenderCV output. The assembler is designed to support either by changing how it groups points, so this is a presentation decision, not a schema decision.

---

## Priority (If Any of These Get Picked Up)

1. **Multi-point detection** — Medium effort. Natural extension of the questioning flow. Requires benchmark fixtures for A/B testing.
2. **Output format variants** — Low effort, high visible impact. Good next feature after the core pipeline works.
3. **Framing technique registry** — Medium effort, good learning value. Requires benchmark fixtures first (ADR-014).
4. **In-context RAG experiments** — Medium effort. Requires benchmark fixtures (ADR-014) and a working customizer engine.
5. **Formal questioning document** — Low effort once patterns stabilize.
6. **Whole-CV enhancements** — Medium effort. Wait until there are enough approved points to make the rules meaningful.
7. **Explicit STAR template** — Low effort if needed. Wait for benchmark data on narrative extraction quality.
