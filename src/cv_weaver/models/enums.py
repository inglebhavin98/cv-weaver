from enum import StrEnum


class ExperienceType(StrEnum):
    EXPERIENCE = "experience"
    PROJECT = "project"
    EDUCATION = "education"
    STATIC = "static"


class ClassificationType(StrEnum):
    GENERAL = "general"
    DOMAIN_SPECIFIC = "domain-specific"
    JD_SPECIFIC = "jd-specific"


class Status(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class Resolution(StrEnum):
    PENDING = "pending"
    KEPT = "kept"
    DISCARDED = "discarded"
    MERGED = "merged"


class GenerationLevel(StrEnum):
    L1 = "l1"
    L2 = "l2"
