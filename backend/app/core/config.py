"""Application Configuration using Pydantic Settings v2."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Core Application
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    DEBUG: bool = True
    PROJECT_NAME: str = "StudyMind"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/studymind"

    # Redis & Task Queue
    REDIS_URL: str = "redis://localhost:6379/0"

    # Vector Database
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NAME: str = "studymind_chunks"

    # Storage
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_DIR: str = "./data/storage"
    S3_ENDPOINT: str | None = "http://localhost:9000"
    S3_BUCKET: str = "studymind"
    S3_ACCESS_KEY: str | None = "minioadmin"
    S3_SECRET_KEY: str | None = "minioadmin"
    S3_REGION: str = "us-east-1"

    # Auth & Security
    JWT_SECRET: str = Field(
        default="insecure-dev-secret-key-change-in-prod-at-least-32-chars",
        description="JWT Secret for signing tokens",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # AI Adapters Configuration
    LLM_PROVIDER: Literal["gemini", "openai", "anthropic", "ollama", "mock"] = "gemini"
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_API_KEY: str | None = None
    LLM_TEMPERATURE: float = 0.0

    VISION_LLM_MODEL: str = "gemini-2.5-flash"

    EMBEDDING_PROVIDER: Literal["bge-m3", "openai", "gemini", "mock"] = "bge-m3"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIMENSION: int = 1024

    RERANKER_PROVIDER: Literal["bge-reranker", "cohere", "mock"] = "bge-reranker"
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    VERIFIER_MODEL: str = "gemini-2.5-flash"

    # Retrieval & Grounding Thresholds
    RETRIEVAL_TOP_K: int = 30
    RERANK_TOP_N: int = 6
    MIN_RELEVANCE_SCORE: float = 0.35
    ENABLE_OUTSIDE_KNOWLEDGE: bool = False

    # Guardrails & Limits
    MAX_UPLOAD_MB: int = 50
    MAX_PAGES: int = 500
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_ENABLED: bool = True

    # Security & Scanning
    ENABLE_MALWARE_SCAN: bool = True
    MAX_ZIP_RATIO: float = 100.0  # Zip bomb decompression ratio protection

    # Observability & Tracing (Langfuse)
    ENABLE_TRACING: bool = True
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # Caching Layer
    ENABLE_CACHE: bool = True
    CACHE_TTL_SECONDS: int = 300  # 5 minutes default TTL
    CACHE_MAX_ENTRIES: int = 1000


settings = Settings()
