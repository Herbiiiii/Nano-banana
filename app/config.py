"""
Конфигурация приложения
"""
from pydantic_settings import BaseSettings
from pydantic import Field
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
    
    # Replicate API (глобальный ключ, если пользователь не указал свой)
    REPLICATE_API_TOKEN: str = Field("", env="REPLICATE_API_TOKEN")
    
    # Performance
    # По умолчанию запускаем только одну генерацию одновременно, чтобы уменьшить вероятность E003/rate-limit
    MAX_WORKERS: int = Field(1, env="MAX_WORKERS")  # Максимум одновременных воркеров
    MAX_CONCURRENT_GENERATIONS: int = Field(1, env="MAX_CONCURRENT_GENERATIONS")  # Лимит активных задач на пользователя
    
    # CORS (для продакшена укажите конкретные домены)
    CORS_ORIGINS: str = Field("*", env="CORS_ORIGINS")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()


