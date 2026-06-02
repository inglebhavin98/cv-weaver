import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, HttpUrl


class Settings(BaseModel):
    """Application configuration loaded from environment variables.

    Values are read from a `.env` file (if present) and OS environment.
    All fields have sensible defaults for local Ollama development.
    """

    ollama_base_url: HttpUrl = Field(default="")
    ollama_api_key: str = Field(default="ollama")
    generation_model: str = Field(default="llama3.2")
    judge_model: str = Field(default="glm-5.1:cloud")
    embedding_model: str = Field(default="nomic-embed-text")
    redundancy_threshold: float = Field(default=0.85)
    use_structured_outputs: bool = Field(default=False, description="Pass Pydantic JSON Schema to Ollama format= (experimental, requires Ollama >= 0.4.x).")
    database_path: Path = Field(default=Path("data/cv_weaver.db"))
    knowledge_base_path: Path = Field(default=Path("data/knowledge_base"))
    output_path: Path = Field(default=Path("data/outputs"))
    # NOTE: RenderCV fields removed — Component 5 (YAML Assembler / PDF) is
    # out of scope. Re-add these when building beyond Component 3.
    # rendercv_yaml_name: str = Field(default="cv-output.yaml")
    # rendercv_pdf_name: str = Field(default="cv-output.pdf")


def load_settings(env_file: Path | str = ".env") -> Settings:
    """Load application settings from a `.env` file and environment variables.

    Args:
        env_file: Path to the `.env` file. Defaults to ".env" in the working directory.

    Returns:
        A validated Settings instance.
    """
    load_dotenv(dotenv_path=env_file, override=True)

    env_mapping = {
        "OLLAMA_BASE_URL": "ollama_base_url",
        "OLLAMA_API_KEY": "ollama_api_key",
        "GENERATION_MODEL": "generation_model",
        "JUDGE_MODEL": "judge_model",
        "EMBEDDING_MODEL": "embedding_model",
        "REDUNDANCY_THRESHOLD": "redundancy_threshold",
        "USE_STRUCTURED_OUTPUTS": "use_structured_outputs",
        "DATABASE_PATH": "database_path",
        "KNOWLEDGE_BASE_PATH": "knowledge_base_path",
        "OUTPUT_PATH": "output_path",
    }

    kwargs = {}
    for env_var, field_name in env_mapping.items():
        value = os.getenv(env_var)
        if value is not None:
            kwargs[field_name] = value

    return Settings(**kwargs)
