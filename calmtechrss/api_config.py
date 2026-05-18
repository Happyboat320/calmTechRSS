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
    timeout_seconds: float = 180.0
    max_retries: int = 5

    @property
    def resolved_api_key(self) -> str:
        return self.api_key or os.getenv(self.api_key_env, "")


@dataclass(frozen=True)
class JudgeSettings:
    enabled: bool = True
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    temperature: float = 0.0
    timeout_seconds: float = 180.0
    max_retries: int = 5

    def resolved(self, llm: LLMSettings) -> LLMSettings:
        return LLMSettings(
            enabled=self.enabled and llm.enabled,
            base_url=self.base_url or llm.base_url,
            api_key_env=self.api_key_env or llm.api_key_env,
            api_key=self.api_key or llm.api_key,
            model=self.model,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )


@dataclass(frozen=True)
class EmbeddingSettings:
    model: str = "intfloat/multilingual-e5-small"
    models: tuple[str, ...] = ("intfloat/multilingual-e5-small", "sentence-transformers/all-MiniLM-L6-v2")
    device: str = "cpu"
    batch_size: int = 32
    cpu_threads: int = 4
    max_chars: int = 2000
    similarity_threshold: float = 0.8


@dataclass(frozen=True)
class PipelineSettings:
    max_workers: int = 4


@dataclass(frozen=True)
class ApiConfig:
    llm: LLMSettings = LLMSettings()
    judge: JudgeSettings = JudgeSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    pipeline: PipelineSettings = PipelineSettings()


def load_api_config(path: str | Path) -> ApiConfig:
    config_path = Path(path)
    if not config_path.exists():
        return ApiConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    llm = raw.get("llm") or {}
    judge = raw.get("judge") or {}
    embedding = raw.get("embedding") or {}
    pipeline = raw.get("pipeline") or {}
    llm_settings = LLMSettings(
        enabled=bool(llm.get("enabled", True)),
        base_url=str(llm.get("base_url", "https://api.openai.com/v1")),
        api_key_env=str(llm.get("api_key_env", "OPENAI_API_KEY")),
        api_key=str(llm.get("api_key", "")),
        model=str(llm.get("model", "gpt-4.1-mini")),
        temperature=float(llm.get("temperature", 0.2)),
        timeout_seconds=float(llm.get("timeout_seconds", 180)),
        max_retries=max(1, int(llm.get("max_retries", 5))),
    )
    embedding_models = tuple(
        str(item)
        for item in embedding.get(
            "models",
            [
                embedding.get("model", "intfloat/multilingual-e5-small"),
                "sentence-transformers/all-MiniLM-L6-v2",
            ],
        )
    )
    if not embedding_models:
        embedding_models = (str(embedding.get("model", "intfloat/multilingual-e5-small")),)
    return ApiConfig(
        llm=llm_settings,
        judge=JudgeSettings(
            enabled=bool(judge.get("enabled", True)),
            base_url=str(judge.get("base_url", "")),
            api_key_env=str(judge.get("api_key_env", "")),
            api_key=str(judge.get("api_key", "")),
            model=str(judge.get("model", "deepseek-v4-flash")),
            temperature=float(judge.get("temperature", 0.0)),
            timeout_seconds=float(judge.get("timeout_seconds", 180)),
            max_retries=max(1, int(judge.get("max_retries", 5))),
        ),
        embedding=EmbeddingSettings(
            model=str(embedding.get("model", "intfloat/multilingual-e5-small")),
            models=embedding_models,
            device=str(embedding.get("device", "cpu")),
            batch_size=int(embedding.get("batch_size", 32)),
            cpu_threads=int(embedding.get("cpu_threads", 4)),
            max_chars=max(1, int(embedding.get("max_chars", 2000))),
            similarity_threshold=float(embedding.get("similarity_threshold", 0.8)),
        ),
        pipeline=PipelineSettings(
            max_workers=max(1, int(pipeline.get("max_workers", 4))),
        ),
    )
