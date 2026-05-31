
### Level 1 (QA): The L1 Judge (Mechanics, Rubrics, and Evals)

The L1 Judge is where you apply the "LLM-as-a-Judge" pattern. It acts as an objective third party that reads the finalized L1 point (after you've finished the QnA loop) and assigns it numerical metadata (`impact_score`, `ats_score`, `completeness_score`).

Here is how to design and utilize this stage effectively.

### 1. How Judging Works (and the Model to Use)

Judging works by providing an LLM with a strict grading rubric and forcing it to output a structured JSON scorecard.

- **The Model:** Since you are running this locally via Ollama, do not use a tiny, fast model (like Llama 3 8B) for judging if you can avoid it. Judging requires deeper semantic reasoning. If your hardware supports it, use a slightly heavier model (like Command-R, Qwen 2 14B/32B, or Mistral Nemo) for the Judge call, even if you use a smaller model for the Drafter.
    
- **The "No Ego" Rule:** The Judge model _must_ be a separate API call from the Drafter. If a model generates text and grades it in the same response, it will hallucinate a perfect 10/10 every time.
    

### 2. The Prompt and Questionnaire (The Rubric)

To get consistent 0-10 numbers, your prompt cannot just say "rate this." You must provide a literal scoring matrix.

You will use `instructor` to force this Pydantic output. Notice the `reasoning` field—forcing the model to explain _why_ it is giving a score before it actually outputs the integer grounds the model and drastically improves scoring accuracy (Chain-of-Thought).

Python

```
class PointScores(BaseModel):
    reasoning: str = Field(description="Step-by-step justification for the scores based on the rubric.")
    impact_score: int = Field(description="0=No result, 5=Vague improvement, 10=Hard business metrics ($, %, time).")
    ats_score: int = Field(description="0=Passive language, 5=Standard verbs/skills, 10=Elite action verbs + heavy skill keywords.")
    completeness_score: int = Field(description="0=Fragment, 5=Missing context, 10=Perfect Situation-Action-Result flow.")
```

### 3. L1 Judge vs. System Evals (The Difference)

It is easy to confuse these two, but they serve completely different architectural purposes:

- **The L1 Judge (Runtime Metadata):** This runs in production on _every single point you generate_. It lives in your SQLite database. Its purpose is to help the L2 Synthesizer and your future Web UI. When you say, "Show me my top 5 backend engineering points," the system just runs a SQL query `ORDER BY impact_score DESC`.
    
- **System Evals (Pipeline Testing):** This runs _offline_ against your `golden_set.jsonl` benchmark fixtures. You run Evals when you want to answer the question: _"If I change the Drafter's system prompt, does the system get better or worse?"_ Evals measure the _engine itself_; the L1 Judge measures the _data_.
    

### 4. How to Use This Effectively

Do not let low L1 Judge scores block your pipeline. The L1 Judge is an observer, not a gatekeeper.

- If a point gets a `3/10` on impact, you still save it to SQLite.
    
- Why? Because later, in the **L2 Synthesis** phase, the system will look at all the points for that experience. It will see the `3/10` point, realize it's weak, and the L2 engine will either merge it into a stronger point or officially drop it, leaving a clean audit trail of _why_ it was dropped.
    

When you are ready, say "next" and we will tackle the **L2 Synthesis** (Deterministic + Semantic rules for merging, splitting, and organizing the batch).




---

# EVALUATION CRITERIA & GRADING RUBRIC
You are a cold, objective automated applicant tracking system (ATS) validator. Grade the provided CV point from 0 to 10 across three vectors. Be conservative; 10s are reserved for flawless production lines.

1. IMPACT SCORE (0-10):
- 0 to 2: No result stated; purely operational task descriptions.
- 3 to 5: Vague improvement noted without verification (e.g., "improving performance").
- 6 to 8: Clear, localized business or engineering metrics included (%, $, time frames).
- 9 to 10: Elite, system-wide scale impact with rigorous quantifiable proof.

2. ATS SCORE (0-10):
- 0 to 2: Contains banned pronouns, passive vocabulary, or lacks an action verb starting sequence.
- 3 to 5: Standard, uninspired verbs used; acronyms are left unexpanded or keywords are stuffed unnaturally.
- 6 to 8: Elite action verbs utilized, technical acronyms properly formatted, and critical skills seamlessly embedded in prose.
- 9 to 10: Flawless layout compatibility, optimal syntax alignment, and high-density professional wording.

3. COMPLETENESS SCORE (0-10):
- 0 to 2: Fragmented sentence or non-compliant format.
- 3 to 5: Missing one core element of the STAR/Situation-Action-Result methodology.
- 6 to 8: Clear presence of Action Verb, Core Task, and Measurable Result in unified prose.
- 9 to 10: Seamless, perfectly proportioned flow detailing the exact technical scope, context, execution, and outcome.

