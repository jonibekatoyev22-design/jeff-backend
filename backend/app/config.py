from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SECRET_KEY: str = "change-me"
    DATABASE_URL: str = "sqlite:///./jeff.db"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    CORS_ORIGINS: str = "http://localhost:5173,https://jeffworld.dev,https://frabjous-kheer-3528af.netlify.app"
    # The platform owner — auto-approved on register, the only account that can approve
    # or reject every other company that signs up. Override via env var in production.
    PLATFORM_OWNER_EMAIL: str = "jonibekatoyev22@gmail.com"
    # Powers the AI Audit Chat drawer (app/routers/ai.py). Either or both may be
    # set — Groq is tried first by default (it's free), OpenAI second, and if the
    # first configured provider's call fails (rate limit, outage), the other one
    # is tried automatically before giving up. With neither set, the chat falls
    # back to the deterministic ASK engine on the frontend — nothing breaks, the
    # AI reply just isn't available yet. Set in Render → Environment, never commit them.
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    OPENAI_MODEL: str = "gpt-4o-mini"
    # Optional override: "groq" or "openai" to force one, instead of auto-preferring Groq.
    AI_PROVIDER: str = ""

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"

settings = Settings()
