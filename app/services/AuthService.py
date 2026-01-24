"""
Сервис аутентификации
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from app.config import settings
from app.models.base import User        
from app.models.token import TokenData, TokenPayload
import logging

logger = logging.getLogger(__name__)
oauth2_scheme = HTTPBearer(auto_error=False)

class AuthService:
    def __init__(self):
        # Убрали passlib, используем только прямой bcrypt
        self.secret_key = settings.SECRET_KEY
        self.algorithm = settings.ALGORITHM
        self.access_token_expire = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        self.refresh_token_expire = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        # Обрезаем пароль до 72 байт при проверке
        password_bytes = self._truncate_password(plain_password)
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)

    def _truncate_password(self, password: str) -> bytes:
        """Обрезает пароль до 72 байт с учетом UTF-8"""
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            # Обрезаем до 72 байт
            password_bytes = password_bytes[:72]
            # Убираем неполные UTF-8 символы в конце
            while len(password_bytes) > 0:
                try:
                    # Проверяем что можем декодировать
                    password_bytes.decode('utf-8')
                    break
                except UnicodeDecodeError:
                    password_bytes = password_bytes[:-1]
        return password_bytes

    def get_password_hash(self, password: str) -> str:
        """Хеширование пароля"""
        # bcrypt ограничение: пароль не может быть длиннее 72 байт
        # Используем прямой вызов bcrypt для обхода проблемы с passlib
        password_bytes = self._truncate_password(password)
        # Генерируем соль и хешируем
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        # Возвращаем как строку (bcrypt возвращает bytes)
        return hashed.decode('utf-8')

    def create_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Создание JWT токена"""
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or self.access_token_expire)
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)

    async def create_access_token(self, user_data: User) -> str:
        """Создание access токена"""
        return self.create_token(
            data={
                "sub": user_data.username,
                "user_id": user_data.id,
                "email": user_data.email,
                "is_active": user_data.is_active,
                "is_admin": user_data.is_admin
            },
            expires_delta=self.access_token_expire
        )

    async def create_refresh_token(self, user_data: User) -> str:
        """Создание refresh токена"""
        return self.create_token(
            data={"sub": user_data.username, "refresh": True},
            expires_delta=self.refresh_token_expire
        )

    async def get_current_user(
        self, 
        credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme)
    ):
        """Получение текущего пользователя из токена"""
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization token missing",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = credentials.credentials
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            token_payload = TokenPayload(
                username=payload.get("sub"),
                user_id=payload.get("user_id"),
                email=payload.get("email"),
                is_active=payload.get("is_active"),
                is_admin=payload.get("is_admin"),
            )

            if not token_payload.username or not token_payload.user_id or not token_payload.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token claims",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return token_payload

        except JWTError as e:
            logger.warning(f"Token decode error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

auth_service = AuthService()

