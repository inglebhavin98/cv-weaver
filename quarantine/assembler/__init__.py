"""Assembler package: builds RenderCV YAML and renders to PDF."""

from .rendercv_integration import RenderCVError, render_pdf
from .yaml_builder import (
    assemble_cv_yaml,
    build_experience_section,
    build_project_section,
    build_skills_section,
    read_profile_yaml,
)

__all__ = [
    "assemble_cv_yaml",
    "build_experience_section",
    "build_project_section",
    "build_skills_section",
    "read_profile_yaml",
    "render_pdf",
    "RenderCVError",
]
