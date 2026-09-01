"""
Схемы данных для Nano Banana Pro API
"""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime

# Аутентификация
class UserCreateRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError('Пароль должен быть не менее 10 символов')
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Пароль слишком длинный (максимум 72 байта)')
        return v

class UserLoginRequest(BaseModel):
    username_or_email: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

# API ключ провайдера (Replicate или Banana Lab), локально на клиенте
class ReplicateApiKeyRequest(BaseModel):
    api_key: str
    provider: Optional[str] = None

class ReplicateApiKeyResponse(BaseModel):
    message: str
    has_key: bool
    has_replicate_key: Optional[bool] = None
    has_bananalab_key: Optional[bool] = None
    has_openrouter_key: Optional[bool] = None
    selected_provider: Optional[str] = None

# Генерация изображений
class ImageGenerationRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    generation_mode: str = "text-to-image"  # "text-to-image" или "image-to-image"
    resolution: str = "1K"  # "1K", "2K", "4K"
    aspect_ratio: str = "1:1"  # "1:1", "16:9", "9:16", "4:3", "3:4"
    guidance_scale: float = 7.5
    num_inference_steps: int = 50
    seed: Optional[int] = None
    reference_images: Optional[List[str]] = None  # URLs или base64 изображений
    api_key: Optional[str] = None  # Replicate (r8_…), Banana Lab (nb_…) или OpenRouter (sk-or_…)
    model_name: Optional[str] = None  # Имя модели (например, "nano-banana-pro", "gemini-2.5-flash-image")

class ImageGenerationResponse(BaseModel):
    status: str
    image_id: Optional[int] = None
    image_url: Optional[str] = None
    message: Optional[str] = None

class ImageResponse(BaseModel):
    id: int
    user_id: int
    prompt: str
    negative_prompt: Optional[str]
    generation_mode: str
    resolution: str
    aspect_ratio: str
    result_url: Optional[str]
    status: str
    created_at: datetime
    error_message: Optional[str] = None
    model_name: Optional[str] = None  # Модель, использованная для генерации
    retry_count: Optional[int] = 0  # Количество уже выполненных ретраев
    max_retries: Optional[int] = 5  # Максимум ретраев для текущей генерации
    fallback_model: Optional[str] = None  # Рекомендуемая fallback-модель для быстрого перезапуска
    
    class Config:
        from_attributes = True

