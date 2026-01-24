"""
Роутер для аутентификации
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
from sqlalchemy import or_
from app.services.AuthService import auth_service
from app.services.DBService import db_service
from app.models.schemas import UserCreateRequest, UserLoginRequest, UserResponse
from app.models.base import User
from app.models.token import Token, TokenPayload

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=Token)
async def register(user_data: UserCreateRequest):
    """Регистрация нового пользователя"""
    with db_service.get_session() as session:
        existing_user = session.query(User).filter(
            or_(
                User.username == user_data.username,
                User.email == user_data.email
            )
        ).first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким именем или email уже существует"
            )

        hashed_password = auth_service.get_password_hash(user_data.password)
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_password,
            is_active=True,
            is_admin=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_login=datetime.utcnow()
        )
        
        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        access_token = await auth_service.create_access_token(new_user)
        refresh_token = await auth_service.create_refresh_token(new_user)

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )

@router.post("/login", response_model=Token)
async def login(user_data: UserLoginRequest):
    """Вход в систему"""
    with db_service.get_session() as session:
        user = session.query(User).filter(
            or_(
                User.username == user_data.username_or_email,
                User.email == user_data.username_or_email
            )
        ).first()

        if not user or not auth_service.verify_password(user_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя/email или пароль"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Аккаунт пользователя отключен"
            )

        user.last_login = datetime.utcnow()
        session.commit()

        access_token = await auth_service.create_access_token(user)
        refresh_token = await auth_service.create_refresh_token(user)

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Получение информации о текущем пользователе"""
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        
        return UserResponse(
            id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            is_active=db_user.is_active,
            is_admin=db_user.is_admin,
            created_at=db_user.created_at
        )

