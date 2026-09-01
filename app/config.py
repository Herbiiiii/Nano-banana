"""
Конфигурация приложения
"""
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
import os

class Settings(BaseSettings):
    # MinIO
    MINIO_ENDPOINT: str = Field("localhost:9000", env="MINIO_ENDPOINT")
    MINIO_ACCESS_KEY: str = Field("minioadmin", env="MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: str = Field("minioadmin123", env="MINIO_SECRET_KEY")
    MINIO_SECURE: bool = Field(False, env="MINIO_SECURE")
    MINIO_BUCKET: str = Field("nano-banana-images", env="MINIO_BUCKET")
    MINIO_PUBLIC_URL: str = Field("http://localhost:9002", env="MINIO_PUBLIC_URL")
    
    # Database
    POSTGRES_HOST: str = Field("localhost", env="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(5432, env="POSTGRES_PORT")
    POSTGRES_DB: str = Field("nano_banana", env="POSTGRES_DB")
    POSTGRES_USER: str = Field("nano_banana_user", env="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field("nano_banana_pass", env="POSTGRES_PASSWORD")
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    # Security
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str = Field("HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(180, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    PWD_SCHEMES: str = Field("bcrypt", env="PWD_SCHEMES")
    
    # BananaLab API
    BANANALAB_API_BASE_URL: str = Field("https://bananahub.app/api", env="BANANALAB_API_BASE_URL")

    # Legacy поле (используется как API key из UI; имя оставлено для совместимости)
    REPLICATE_API_TOKEN: str = Field("", env="REPLICATE_API_TOKEN")

    # Banana Lab (Nano Banana HTTP API)
    BANANALAB_BASE_URL: str = Field("https://bananahub.app/api", env="BANANALAB_BASE_URL")

    @field_validator("BANANALAB_BASE_URL", "BANANALAB_API_BASE_URL", mode="before")
    @classmethod
    def _normalize_bananahub_domain(cls, value):
        """Старый bananahub.io не резолвится — принудительно .app."""
        if isinstance(value, str):
            return value.replace("bananahub.io", "bananahub.app")
        return value
    
    # BananaHub: «Upstream returned no image» — flaky Gemini; ТП рекомендует несколько повторов
    BANANALAB_UPSTREAM_NO_IMAGE_MAX_RETRIES: int = Field(
        5, env="BANANALAB_UPSTREAM_NO_IMAGE_MAX_RETRIES"
    )
    BANANALAB_UPSTREAM_NO_IMAGE_RETRY_BASE_DELAY_SECONDS: float = Field(
        3.0, env="BANANALAB_UPSTREAM_NO_IMAGE_RETRY_BASE_DELAY_SECONDS"
    )

    # OpenRouter Image API (sk-or_…)
    OPENROUTER_HTTP_REFERER: str = Field("", env="OPENROUTER_HTTP_REFERER")
    OPENROUTER_X_TITLE: str = Field("Nano Banana Pro", env="OPENROUTER_X_TITLE")

    # Performance
    # По умолчанию запускаем только одну генерацию одновременно, чтобы уменьшить вероятность E003/rate-limit
    MAX_WORKERS: int = Field(1, env="MAX_WORKERS")  # Максимум одновременных воркеров
    MAX_CONCURRENT_GENERATIONS: int = Field(1, env="MAX_CONCURRENT_GENERATIONS")  # Лимит активных задач на пользователя
    
    # CORS (для продакшена укажите конкретные домены)
    CORS_ORIGINS: str = Field("*", env="CORS_ORIGINS")
    API_URL: str = Field("http://localhost:8000", env="API_URL")

    # Security hardening
    SECURITY_STRICT_CSP: bool = Field(True, env="SECURITY_STRICT_CSP")
    SECURITY_ENABLE_HSTS: bool = Field(True, env="SECURITY_ENABLE_HSTS")
    SECURITY_LOGIN_MAX_ATTEMPTS: int = Field(10, env="SECURITY_LOGIN_MAX_ATTEMPTS")
    SECURITY_LOGIN_WINDOW_SECONDS: int = Field(300, env="SECURITY_LOGIN_WINDOW_SECONDS")
    SECURITY_ADMIN_READ_MAX_REQUESTS: int = Field(120, env="SECURITY_ADMIN_READ_MAX_REQUESTS")
    SECURITY_ADMIN_READ_WINDOW_SECONDS: int = Field(60, env="SECURITY_ADMIN_READ_WINDOW_SECONDS")
    SECURITY_CSP_ALLOW_INLINE_SCRIPTS: bool = Field(True, env="SECURITY_CSP_ALLOW_INLINE_SCRIPTS")
    SECURITY_CSP_ALLOW_MINIO_CONSOLE_FRAME: bool = Field(False, env="SECURITY_CSP_ALLOW_MINIO_CONSOLE_FRAME")
    SECURITY_DISABLE_OPENAPI: bool = Field(False, env="SECURITY_DISABLE_OPENAPI")
    SECURITY_REGISTER_MAX_ATTEMPTS: int = Field(10, env="SECURITY_REGISTER_MAX_ATTEMPTS")
    SECURITY_REGISTER_WINDOW_SECONDS: int = Field(3600, env="SECURITY_REGISTER_WINDOW_SECONDS")
    # Доп. хосты для reference URL (через запятую), помимо MINIO_PUBLIC_URL и API_URL
    SECURITY_ALLOWED_REF_URL_HOSTS: str = Field("", env="SECURITY_ALLOWED_REF_URL_HOSTS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()


