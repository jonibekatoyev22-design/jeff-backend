from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SECRET_KEY: str = "change-me"
    DATABASE_URL: str = "sqlite:///./jeff.db"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    CORS_ORIGINS: str = "http://localhost:5173,https://jeffworld.dev,https://frabjous-kheer-3528af.netlify.app"
    # The platform owner — auto-approved on register, the only account that can approve
    # or reject every other company that signs up. Override via env var in production.
    PLATFORM_OWNER_EMAIL: str = "jonibekatoyev22@gmail.com"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"

settings = Settings()
