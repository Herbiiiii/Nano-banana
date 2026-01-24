"""
FastAPI приложение для Nano Banana Pro
Адаптировано из ai SITE проекта
"""
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from app.routers import images, auth, users
from app.services.DBService import db_service
import logging
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Nano Banana Pro API",
    description="API для генерации изображений через Nano Banana Pro (Replicate)",
    version="1.0.0"
)

# CORS настройки (должен быть первым)
# ВАЖНО: Для продакшена замените ["*"] на конкретные домены, например:
# allow_origins=["https://yourdomain.com", "https://www.yourdomain.com"]
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",") if os.getenv("CORS_ORIGINS") else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware для установки CSP заголовков
class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Получаем настройки из переменных окружения
        api_url = os.getenv("API_URL", "http://localhost:8000")
        minio_url = os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000")
        minio_console_url = os.getenv("MINIO_CONSOLE_URL", "http://localhost:9001")
        
        # Для продакшена используйте более строгую политику
        # ВАЖНО: Настройте CSP для вашего домена в продакшене
        csp_policy = (
            f"default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: {api_url}; "
            f"img-src 'self' data: blob: {minio_url} https://replicate.delivery https://*.replicate.delivery http://* https://*; "
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {api_url} https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            f"style-src 'self' 'unsafe-inline' {api_url} https://cdn.jsdelivr.net https://cdnjs.cloudflare.com http://* https://*; "
            f"font-src 'self' data: {api_url} https://cdn.jsdelivr.net https://cdnjs.cloudflare.com http://* https://*; "
            f"connect-src 'self' {api_url} {minio_url} https://replicate.delivery https://*.replicate.delivery https://api.replicate.com http://* https://*; "
            f"frame-src 'self' {minio_console_url};"
        )
        response.headers["Content-Security-Policy"] = csp_policy
        return response

# Добавляем CSP middleware (после CORS)
app.add_middleware(CSPMiddleware)

# Обработчик ошибок валидации для логирования
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Обработчик ошибок валидации с подробным логированием"""
    logger.error(f"[VALIDATION] Ошибка валидации для {request.method} {request.url}")
    logger.error(f"[VALIDATION] Детали ошибки: {exc.errors()}")
    logger.error(f"[VALIDATION] Тело запроса: {await request.body()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()}
    )

# Инициализация БД при старте
@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске приложения"""
    try:
        db_service.create_tables()
        logger.info("[STARTUP] База данных инициализирована")
    except Exception as e:
        logger.error(f"[STARTUP] Ошибка инициализации БД: {e}")

# Health check endpoint (должен быть до статических файлов)
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api")
async def api_info():
    return {
        "message": "Nano Banana Pro API",
        "version": "1.0.0",
        "docs": "/docs"
    }

# Подключение роутеров
app.include_router(auth.router, prefix="/api/v1")
app.include_router(images.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")

# Статические файлы (frontend) - монтируем после роутов
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_path):
    # Создаем кастомный класс для отключения кэширования статических файлов
    class NoCacheStaticFiles(StaticFiles):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
        
        async def __call__(self, scope, receive, send):
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    # Отключаем кэширование для JS и CSS файлов
                    headers = dict(message.get("headers", []))
                    if any(key.lower() == b"content-type" and (
                        b"javascript" in headers[key].lower() or 
                        b"css" in headers[key].lower() or
                        b"text/html" in headers[key].lower()
                    ) for key in headers):
                        headers[b"cache-control"] = b"no-cache, no-store, must-revalidate"
                        headers[b"pragma"] = b"no-cache"
                        headers[b"expires"] = b"0"
                    message["headers"] = list(headers.items())
                await send(message)
            await super().__call__(scope, receive, send_wrapper)
    
    app.mount("/", NoCacheStaticFiles(directory=frontend_path, html=True), name="frontend")
    logger.info(f"[STARTUP] Статические файлы подключены из {frontend_path} (кэширование отключено)")

