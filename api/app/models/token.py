"""
Модели токенов
"""
from pydantic import BaseModel
from typing import Optional

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    username: Optional[str] = None

class TokenPayload(BaseModel):
    username: str
    user_id: int
    email: str
    is_active: bool
    is_admin: bool

