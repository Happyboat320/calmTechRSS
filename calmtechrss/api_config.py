from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import yaml


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool = True
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    temperature: float = 0.2
    timeout_seconds: float = 60.0

    @property
    def resolved_api_key(self) -> str:
        return self.api_key or os.getenv(self.api_key_env, "")


@dataclass(frozen=True)
class EmbeddingSettings:
    model: str = "intfloat/multilingual-e5-small"


@dataclass(frozen=True)
class ApiConfig:
    llm: LLMSettings = LLMSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()


def load_api_config(path: str | Path) -> ApiConfig:
    config_path = Path(path)
    if not config_path.exists():
        return ApiConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    llm = raw.get("llm") or {}
    embedding = raw.get("embedding") or {}
    return ApiConfig(
        llm=LLMSettings(
            enabled=bool(llm.get("enabled", True)),
            base_url=str(llm.get("base_url", "https://api.openai.com/v1")),
            api_key_env=str(llm.get("api_key_env", "OPENAI_API_KEY")),
            api_key=str(llm.get("api_key", "")),
            model=str(llm.get("model", "gpt-4.1-mini")),
            temperature=float(llm.get("temperature", 0.2)),
            timeout_seconds=float(llm.get("timeout_seconds", 60)),
        ),
        embedding=EmbeddingSettings(
            model=str(embedding.get("model", "intfloat/multilingual-e5-small")),
        ),
    )

