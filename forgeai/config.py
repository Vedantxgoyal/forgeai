"""Runtime configuration.

Every setting can be overridden with an environment variable prefixed ``FORGE_``
(or a ``.env`` file). The LLM endpoint is any OpenAI-compatible server, so the
same code runs against local Ollama or a hosted open-model API such as Groq.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGE_", env_file=".env", extra="ignore")

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"

    gen_model: str = "qwen2.5:7b-instruct"
    judge_model: str = "llama3.1:8b"
    agent_model: str = ""
    fallback_models: str = ""
    local_base_url: str = "http://localhost:11434/v1"
    judge_fallback_models: str = ""
    max_quota_wait_s: float = 0

    request_timeout_s: float = 180.0
    transport_retries: int = 3
    json_retries: int = 2
    seed: int = 7

    token_budget: int = 0

    embed_backend: str = Field(default="auto", pattern="^(auto|st|ollama|tfidf)$")
    st_model: str = "BAAI/bge-small-en-v1.5"
    st_reranker: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ollama_embed_model: str = "nomic-embed-text"

    cache_dir: Path = Path(".forge_cache")
    use_cache: bool = True

    @property
    def effective_agent_model(self) -> str:
        return self.agent_model or self.gen_model

    @property
    def ollama_native_url(self) -> str:
        """Ollama's native API root (without the /v1 OpenAI shim)."""
        url = self.llm_base_url.rstrip("/")
        return url[:-3] if url.endswith("/v1") else url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
