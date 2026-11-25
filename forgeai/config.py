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

    # --- LLM endpoint (OpenAI-compatible) ---------------------------------
    llm_base_url: str = "http://localhost:11434/v1"  # Ollama default
    llm_api_key: str = "ollama"  # Ollama ignores it; Groq needs a real key

    # Generator writes requirements, prompts, evals, fixes.
    gen_model: str = "qwen2.5:7b-instruct"
    # Judge is deliberately a different model family (self-preference defence).
    judge_model: str = "llama3.1:8b"
    # Model the produced agent runs on. Empty -> same as gen_model.
    agent_model: str = ""
    # Comma-separated stand-ins used when a model's quota is spent or it does not exist, in order.
    # "name@local" means: ask the local endpoint (Ollama) instead. Every substitution is reported.
    fallback_models: str = ""
    local_base_url: str = "http://localhost:11434/v1"

    request_timeout_s: float = 180.0
    transport_retries: int = 3  # network / rate-limit retries per call
    json_retries: int = 2  # schema-repair retries per structured call
    seed: int = 7

    # --- Budget (0 = unlimited) -------------------------------------------
    token_budget: int = 0

    # --- Embeddings ---------------------------------------------------------
    # auto -> sentence-transformers, then Ollama, then TF-IDF/LSA fallback.
    embed_backend: str = Field(default="auto", pattern="^(auto|st|ollama|tfidf)$")
    st_model: str = "BAAI/bge-small-en-v1.5"
    st_reranker: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ollama_embed_model: str = "nomic-embed-text"

    # --- Storage ----------------------------------------------------------
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
