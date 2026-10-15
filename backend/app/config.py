"""
Application configuration using pydantic-settings.
All values are loaded from environment variables (or .env file).
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────────────────────
    APP_NAME: str = "RAG Agent API"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"         # development | staging | production
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── LLM Configuration (Configurable, No hardcoding) ────────────────────────
    PRIMARY_LLM_PROVIDER: str = "groq"       # "groq" | "gemini" | "auto"
    PRIMARY_LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_TEMPERATURE: float = 0.1
    LLM_PROVIDER: str = "auto"

    # ── Fallback LLM Configuration ─────────────────────────────────────────────
    ENABLE_LLM_FALLBACK: bool = True
    FALLBACK_LLM_PROVIDER: str = "groq"       # default fallback provider: "groq" | "gemini"
    FALLBACK_LLM_MODELS: str = "llama-3.1-8b-instant, mixtral-8x7b-32768, gemma2-9b-it"  # comma-separated chain of fallbacks
    FALLBACK_LLM_MODEL: str = "llama-3.1-8b-instant"
    FALLBACK_LLM_TEMPERATURE: float = 0.1

    # ── Provider Specific Keys & Models ────────────────────────────────────────
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    GOOGLE_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    EMBEDDING_DIMENSION: int = 3072          # gemini-embedding-001 output dimension
    EMBEDDING_BATCH_SIZE: int = 5          # chunks per embed API call

    # ── RAG retrieval ───────────────────────────────────────────────────────────
    RETRIEVAL_TOP_K: int = 5                # default chunks to retrieve per query
    RETRIEVAL_MIN_SCORE: float = 0.63        # minimum cosine similarity score threshold
    RETRIEVAL_MAX_GAP: float = 0.05          # maximum score difference from top score to keep a candidate
    QUERY_REWRITE_ENABLED: bool = True       # rewrite follow-up questions into standalone search queries
    QUERY_REWRITE_MODEL: str = "llama-3.1-8b-instant"   # small, fast Groq model for that rewrite
    MAX_HISTORY_PAIRS: int = 3             # conversation turns kept in context window

    # ── Embedding Resiliency ──────────────────────────────────────────────────
    MAX_EMBED_RETRIES: int = 5
    INITIAL_BACKOFF: float = 1.0
    MAX_BACKOFF: float = 16.0
    ENABLE_JITTER: bool = True
    MAX_CONCURRENT_EMBEDDINGS: int = 1


    # ── PostgreSQL ─────────────────────────────────────────────────────────────
    DATABASE_URL: str | None = None
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "raguser"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "ragdb"

    @property
    def postgres_dsn(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            
            from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
            parsed = urlparse(url)
            if parsed.query:
                # asyncpg only accepts specific parameters; filter out channel_binding, sslmode, etc.
                allowed_params = {
                    "ssl", "timeout", "command_timeout", "statement_cache_size",
                    "max_cached_statement_lifetime", "max_cacheable_statement_size",
                    "server_settings"
                }
                query_params = parse_qsl(parsed.query)
                new_params = []
                ssl_set = False
                for k, v in query_params:
                    if k == "sslmode":
                        if v != "disable" and not ssl_set:
                            new_params.append(("ssl", "require"))
                            ssl_set = True
                    elif k == "ssl":
                        new_params.append((k, v))
                        ssl_set = True
                    elif k in allowed_params:
                        new_params.append((k, v))
                url = urlunparse(parsed._replace(query=urlencode(new_params)))
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        """Sync DSN used for health-check ping only."""
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return url
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Qdrant ─────────────────────────────────────────────────────────────────
    QDRANT_URL: str | None = None
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None        # optional; required for Qdrant Cloud
    QDRANT_COLLECTION: str = "documents"

    @property
    def qdrant_url(self) -> str:
        if self.QDRANT_URL:
            return self.QDRANT_URL
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    # ── Upload limits ──────────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 50            # per-file size limit
    MAX_FILES_PER_UPLOAD: int = 10
    # ── Auth ──────────────────────────────────────────────────────────────────
    JWT_SECRET: str | None = None           # REQUIRED in production; a random one is used (with a warning) if unset
    JWT_EXPIRE_HOURS: int = 24 * 7
    # How many reverse proxies sit in front of the app (Render's load balancer = 1). The client address is
    # taken from the Nth entry from the END of X-Forwarded-For, which only trusted proxies write; entries
    # further left are supplied by the client and can be forged. Raise it if logs show every user sharing one IP.
    TRUSTED_PROXY_HOPS: int = 1
    # Optional: read the client address from this header instead (e.g. "cf-connecting-ip", which Cloudflare
    # always overwrites). Only set it if your proxy really sets it; verify with the admin network check.
    CLIENT_IP_HEADER: str = ""
    # True when a frontend proxy that you trust (e.g. Vercel, which overwrites X-Forwarded-For with the visitor's
    # address) sits in front of this API. Visitors are then told apart by the address it forwards instead of all
    # sharing the proxy's. Someone calling the API directly can forge it, so the connecting address is also
    # limited, loosely. Leave false if the API is reached directly by browsers.
    FRONTEND_FORWARDS_CLIENT_IP: bool = False
    # The administrator account. Set BOTH: the account is created (or its password reset) at startup and is the
    # only admin. Registering this address through the sign-up form never grants admin rights.
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""
    ALLOW_SIGNUP: bool = True               # set false to close registration
    QUERY_DAILY_LIMIT: int = 100            # chat questions per user per 24h (0 = unlimited); the admin is exempt
    UPLOAD_DAILY_LIMIT: int = 50            # files uploaded per user per 24h (0 = unlimited); the admin is exempt
    RESUME_EDITS_PER_HOUR: int = 60         # re-scores and bullet rewrites per user per hour (each compiles or calls the LLM)
    RESUME_DAILY_LIMIT: int = 20           # tailoring runs per user per 24h (protects the shared LLM quota)

    # ── Images ────────────────────────────────────────────────────────────────
    CHAT_MAX_IMAGES: int = 3                 # images attached to one chat question
    CHAT_IMAGE_MAX_BYTES: int = 4 * 1024 * 1024   # per image, after the browser's own downscaling
    IMAGE_MAX_PIXELS: int = 25_000_000       # refuse anything larger: bombs, and a 512 MB server can't decode more
    IMAGE_CAPTION_MAX_PER_DOC: int = 6       # AI captions generated per uploaded document (quota/time)
    MAX_ASSETS_PER_DOC: int = 40             # figures kept per document
    VISION_REQUESTS_PER_HOUR: int = 40       # per user: image questions + code-screenshot reads

    RESUME_ATS_THRESHOLD: int = 82          # LaTeX/PDF are released only at or above this ATS score
    GITHUB_TOKEN: str | None = None        # optional: private repos + higher GitHub rate limit

    # ── PDF Chunking ────────────────────────────────────────────────────────────
    MIN_CHUNK_SIZE: int = 500              # target minimum chars per chunk
    MAX_CHUNK_SIZE: int = 2000             # max chars before recursive split
    CHUNK_OVERLAP: int = 200               # chars shared between consecutive chunks

    # ── CORS ───────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["*"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of Settings."""
    return Settings()  # type: ignore[call-arg]
