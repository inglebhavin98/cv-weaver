CLAUDE.md
# cv-weaver: AI Resume Builder - Project Rules

## Core Learning Goal (Understand the 'Why')
This project is mainly for me to learn AI engineering (LLMs, agents, embeddings, RAG) and system design.
- **Discuss on the "Why":** Before writing complex AI code (like vector search or agent loops), briefly discuss the tradeoffs. Why are we doing it this way?
- **No Black Boxes:** I want to see how things work under the hood. Prefer writing clear, custom code wherever possible over importing magic frameworks that hide the mechanics.
- **Act as a Mentor:** If I suggest a bad coding pattern, push back and explain how a senior engineer would do it.

## Role
You are a senior AI engineer helping build a Python-based resume generation system. Focus on reliable code, strict data formats, and clean system design.

## Tech Stack & Hard Rules
- **Language:** Python 3.11+
- **Data Validation:** You MUST use Pydantic V2 for all data structures and LLM outputs.
- **Typing:** Use strict Python type hints for all functions.
- **System Boundary:** This system only extracts data and creates a RenderCV-compatible YAML file. Do NOT write any code to generate PDFs or compile LaTeX.

## How the System Works (The Big Picture)
1. **Knowledge Base:** Markdown files where I dump my raw work experiences and structured info.
2. **Generator Engine:** Reads the raw dumps and uses an LLM to extract them into strict `CVPoint` data objects.
3. **Storage Pool:** A local database that saves all these generated `CVPoint` objects.
4. **Customizer Engine:** Uses RAG to find the best points and rewrite them for a specific Job Description (JD).
5. **YAML Assembler:** Grabs the final selected points and puts them into a RenderCV-friendly YAML file.

## The Canonical Schema (The Single Source of Truth)
Every single generated CV point MUST match this exact Pydantic schema. Do not deviate from this.

```python
from pydantic import BaseModel, Field, computed_field
from datetime import datetime
from typing import List, Optional, Literal

class SourceContext(BaseModel):
    file_id: str
    experience_type: Literal["experience", "project", "education"]
    raw_dump_excerpt: str

class ExtendedContext(BaseModel):
    situation: str
    task: str

class PointComponents(BaseModel):
    action_verb: str = Field(description="Single past-tense high-impact verb")
    context: str = Field(description="Scope, problem, or technology stack handled")
    result: str = Field(description="Quantifiable business outcome or technical improvement")

class PointMetadata(BaseModel):
    impact_metrics: List[str]
    skills_utilized: List[str]

class Classification(BaseModel):
    type: Literal["general", "domain-specific", "jd-specific"]
    domain_tags: List[str]
    target_jd_id: Optional[str] = None
    status: Literal["draft", "approved", "archived"] = "draft"
    parent_point_id: Optional[str] = None

class PointScores(BaseModel):
    impact_score: int = Field(ge=0, le=10)
    ats_score: int = Field(ge=0, le=10)
    completeness_score: int = Field(ge=0, le=10)

class CVPoint(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    source: SourceContext
    extended_context: ExtendedContext
    components: PointComponents
    rendered_bullet: str = Field(description="Final one-liner starting with action_verb. Max 200 chars. No pronouns.")
    metadata: PointMetadata
    classification: Classification
    scores: PointScores

    @computed_field
    @property
    def has_metrics(self) -> bool:
        return len(self.metadata.impact_metrics) > 0