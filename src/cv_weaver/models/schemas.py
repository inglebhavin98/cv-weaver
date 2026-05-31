import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Self

from pydantic import BaseModel, Field, computed_field

from .enums import ClassificationType, ExperienceType, GenerationLevel, Status


class SourceContext(BaseModel):
    file_id: str
    experience_type: ExperienceType
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
    type: ClassificationType
    domain_tags: List[str]
    target_jd_id: Optional[str] = None
    status: Status = Status.DRAFT
    parent_point_id: Optional[str] = None


class PointScores(BaseModel):
    impact_score: int = Field(ge=0, le=10)
    ats_score: int = Field(ge=0, le=10)
    completeness_score: int = Field(ge=0, le=10)


class CVPoint(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: SourceContext
    extended_context: ExtendedContext
    components: PointComponents
    rendered_bullet: str = Field(
        description="Final one-liner starting with action_verb. Max 200 chars. No pronouns."
    )
    metadata: PointMetadata
    classification: Classification
    scores: PointScores
    generation_level: GenerationLevel = GenerationLevel.L1

    @computed_field
    @property
    def has_metrics(self) -> bool:
        return len(self.metadata.impact_metrics) > 0

    def to_sqlite_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "source_file_id": self.source.file_id,
            "source_type": self.source.experience_type.value,
            "raw_dump_excerpt": self.source.raw_dump_excerpt,
            "situation": self.extended_context.situation,
            "task": self.extended_context.task,
            "action_verb": self.components.action_verb,
            "context": self.components.context,
            "result": self.components.result,
            "rendered_bullet": self.rendered_bullet,
            "impact_metrics": json.dumps(self.metadata.impact_metrics),
            "skills_utilized": json.dumps(self.metadata.skills_utilized),
            "classification_type": self.classification.type.value,
            "domain_tags": json.dumps(self.classification.domain_tags),
            "target_jd_id": self.classification.target_jd_id,
            "status": self.classification.status.value,
            "parent_point_id": self.classification.parent_point_id,
            "impact_score": self.scores.impact_score,
            "ats_score": self.scores.ats_score,
            "completeness_score": self.scores.completeness_score,
            "generation_level": self.generation_level.value,
        }

    @classmethod
    def from_sqlite_row(cls, row: sqlite3.Row) -> Self:
        metadata = PointMetadata(
            impact_metrics=json.loads(row["impact_metrics"]),
            skills_utilized=json.loads(row["skills_utilized"]),
        )
        return cls(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source=SourceContext(
                file_id=row["source_file_id"],
                experience_type=ExperienceType(row["source_type"]),
                raw_dump_excerpt=row["raw_dump_excerpt"],
            ),
            extended_context=ExtendedContext(
                situation=row["situation"],
                task=row["task"],
            ),
            components=PointComponents(
                action_verb=row["action_verb"],
                context=row["context"],
                result=row["result"],
            ),
            rendered_bullet=row["rendered_bullet"],
            metadata=metadata,
            classification=Classification(
                type=ClassificationType(row["classification_type"]),
                domain_tags=json.loads(row["domain_tags"]),
                target_jd_id=row["target_jd_id"],
                status=Status(row["status"]),
                parent_point_id=row["parent_point_id"],
            ),
            scores=PointScores(
                impact_score=row["impact_score"],
                ats_score=row["ats_score"],
                completeness_score=row["completeness_score"],
            ),
            generation_level=GenerationLevel(row["generation_level"]),
        )
