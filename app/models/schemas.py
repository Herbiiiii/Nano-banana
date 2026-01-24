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
        if len(v) < 6:
            raise ValueError('Пароль должен быть не менее 6 символов')
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

# API ключ Replicate
class ReplicateApiKeyRequest(BaseModel):
    api_key: str

class ReplicateApiKeyResponse(BaseModel):
    message: str
    has_key: bool

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
    api_key: Optional[str] = None  # API ключ Replicate (не сохраняется в БД, используется только в сессии)

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
    
    class Config:
        from_attributes = True

