
### Level 1 (QnA): Mechanics, Checklists, and Loop Execution

#### Step 1: The Programmatic Checklist (Python Rules)

Before wasting an LLM call to find errors, run your compiled CVPointCandidate through standard Python code functions in validation_rules.py.

You check for hard constraints: Does it contain "I" or "we"? Is it longer than 200 characters? Is the impact_metrics list empty?

The Action: If a hard constraint fails (e.g., empty metrics), your code automatically generates a pre-formatted template question: "I noticed this point lacks a quantifiable metric. Can you provide a number, percentage, or scale?" This bypasses an entire LLM call.
#### Step 2: The Interrogator Call (LLM Checklist)

If your programmatic checks pass, the point is structurally sound but might be semantically weak. You pass the raw story and the draft point to the Interrogator Prompt, giving it a strict checklist to evaluate:

The Context Gap: Does the draft drop key tech stack details mentioned in the story?

The Logic Gap: Does the result make sense given the action? (e.g., "changed a CSS variable" leading to "₹5M revenue increase" is a logical stretch).

The Interrogator is forced via instructor to return a strict JSON schema:

Python
class InterrogationResult(BaseModel):
    has_critical_gap: bool
    detected_gap_type: Literal["metric", "technology", "scope", "none"]
    targeted_question: Optional[str] = Field(description="A single, direct question to fix the gap.")
If has_critical_gap is False, the loop breaks instantly.
#### Step 3: The CLI Intermission (Human-in-the-Loop)

If either Step 1 or Step 2 generates a question, the terminal pauses execution and prints:

Plaintext

```
Current Draft: [Optimized database queries to improve payment processing speed.]
Question: How much did the processing speed improve, or what was the original latency?
Your Answer (or press Enter to skip / accept current draft): 
```

#### Step 4: The Refiner Call & Loop State

If you type an answer, the system bundles the **Raw Story + Current Draft + Question + Your Answer** and passes it to the **Refiner Prompt**. This prompt has one explicit instruction: _Rewrite the draft point to incorporate the new answer, while strictly maintaining the canonical schema rules._

The Refiner outputs a fresh `CVPointCandidate`, and the sequence restarts at Step 1.

### Managing the State and Preventing Infinite Loops

To ensure this loop remains stable, you enforce three core state-management rules in your code:

- **The Max-Cap Guard:** You pass a state variable `current_round: int` through the loop. If `current_round == 3`, the loop forcefully terminates and saves the current draft, preventing the LLM from trapping you.
- **The Escape Hatch:** If the user writes "good enough," we immediately exit
- **State Immutability:** The raw story never changes. The user's input is appended to a temporary list of `user_clarifications: List[str]` inside the session state, so the model retains memory of what you said in round 1 when it processes round 2.

---



-gemini:


### 1. QnA SOP Design: Rule-Based vs. LLM Generation

**Rule-Based Triggers (Run these first):**

These are simple `if` statements executed against your Pydantic `CVPointCandidate`.

- **Trigger:** `len(impact_metrics) == 0`
    
    - **Question:** "Can you quantify the result of this? (e.g., 'saved 10 hours/week', 'increased efficiency by 15%', 'managed ₹50,000')."
        
- **Trigger:** `action_verb` is weak (e.g., "Helped", "Worked", "Did"). You can check this against a hardcoded list of banned verbs.
    
    - **Question:** "The verb '{verb}' is passive. Did you 'Architect', 'Manage', 'Develop', or 'Lead' this instead?"
        

**LLM-Generated Triggers (Run if rules pass, but semantic gaps exist):**

Use a specific "Interrogator Prompt" that takes the draft point and the raw story, looking for logic gaps.

- **System Prompt Template:**
    
    > "You are an expert resume reviewer. Read the user's raw story and the generated draft CV point. Identify exactly ONE critical missing piece of context in the draft that was hinted at in the raw story (e.g., missing team size, unclear technology stack, or vague business impact). Generate a single, direct question to ask the user to extract this specific detail. If the point is already excellent, output 'NONE'."
    
### 4. Level 2 Refinement Prompt (Final Points + Reasoning)

To force the LLM to provide its reasoning _before_ giving you the final points, you must use Pydantic's structured outputs to enforce a Chain-of-Thought.

Instead of asking the LLM to just output points, force it to output this specific schema during Level 2:

Python

```
class RefinedPointNode(BaseModel):
    editorial_reasoning: str = Field(description="Explain why points were merged, split, or dropped to create this final point.")
    final_point: CVPoint
    
class LevelTwoOutput(BaseModel):
    refined_points: List[RefinedPointNode]
```

Because LLMs generate tokens sequentially, forcing the `editorial_reasoning` key to appear first in the JSON object makes the model "think out loud" before it commits to the data in the `final_point` object. This drastically reduces hallucinations and illogical merges.

### 5. Benchmark Fixtures (Setting the Ground Truth)

To evaluate your pipeline effectively, you need a static dataset that never changes.

Create a `data/benchmarks/golden_set.jsonl` file. You need to manually write 10 to 20 perfect pairs. This represents the absolute highest standard of what you want the system to output.

**Format:**

JSON

```
{"raw_story": "I worked on the AI bug triage system and used RAG to make it better. It took less time for the team to find bugs.", "gold_action_verb": "Architected", "gold_rendered_bullet": "Architected a retrieval-augmented generation (RAG) bug triage system, reducing team resolution time.", "expected_skills": ["RAG", "AI"]}
```

When you tweak your Generator Engine prompts or change your LLM from Anthropic to an Ollama local model, you run a script that feeds the `raw_story` to the engine, and then uses a programmatic string comparison (or an LLM-as-a-judge) to score how close the engine's output got to your `gold_rendered_bullet`.



---

# INTERROGATION INSTRUCTIONS
Evaluate the generated draft CV point against the raw narrative story and the strict baseline writing constraints. You must check for the following flaws:

1. Structural Completeness: Is any phase of the [Action Verb], [Core Task], or [Measurable Result] sequence missing?
2. Vocabulary Check: Does the point contain pronouns (I, me, we) or banned passive vocabulary ("responsible for", "helped with", "worked on")?
3. Tense Match: Is a past experience incorrectly using present tense, or a current experience missing proper present-tense implementation?
4. Acronym Expansion: Is there a technical acronym used that is not spelled out completely with its parentheses pairing?

If any of these gaps are found, output `has_critical_gap: true` and write a targeted, single question via the terminal to prompt the user for the missing context or metric.