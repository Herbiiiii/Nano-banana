"""
Роутер для управления пользователями и API ключами
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import ReplicateApiKeyRequest, ReplicateApiKeyResponse, UserResponse
from app.services.DBService import db_service
from app.services.AuthService import auth_service
from app.models.base import User
from app.models.token import TokenPayload
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

@router.put("/api-key", response_model=ReplicateApiKeyResponse)
async def set_replicate_api_key(
    request: ReplicateApiKeyRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    ВАЖНО: API ключи НЕ сохраняются в БД для безопасности.
    Ключ используется только в текущей сессии пользователя.
    Пользователь должен вводить ключ при каждом использовании или хранить его локально.
    """
    # Ключи НЕ сохраняются в БД - возвращаем только подтверждение
    logger.info(f"[USER] API ключ получен для пользователя {user.user_id} (не сохраняется в БД)")
    
    return ReplicateApiKeyResponse(
        message="API ключ принят (не сохраняется в БД для вашей безопасности)",
        has_key=True
    )

@router.get("/api-key", response_model=ReplicateApiKeyResponse)
async def get_replicate_api_key_status(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    ВАЖНО: API ключи НЕ сохраняются в БД.
    Всегда возвращает has_key=False, так как ключи не хранятся на сервере.
    """
    return ReplicateApiKeyResponse(
        message="API ключи не сохраняются на сервере для вашей безопасности",
        has_key=False
    )

@router.delete("/api-key")
async def delete_replicate_api_key(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    ВАЖНО: API ключи НЕ сохраняются в БД, поэтому удалять нечего.
    Ключ должен быть удален на стороне клиента (localStorage/sessionStorage).
    """
    logger.info(f"[USER] Запрос на удаление API ключа от пользователя {user.user_id} (ключи не хранятся в БД)")
    return {"message": "API ключи не хранятся на сервере, удалите ключ на стороне клиента"}


