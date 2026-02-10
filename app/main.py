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
from logging.handlers import RotatingFileHandler
from app.services.ErrorLogger import get_logs_dir, save_error_to_file
import asyncio
from datetime import datetime, timedelta
from typing import List
from app.models.base import Generation
from app.services.MinioService import MinioService
from app.config import settings as app_settings

# Создаем папки для логов если их нет
logs_dir = get_logs_dir()
os.makedirs(logs_dir, exist_ok=True)

# Настройка логирования в файл с ротацией (лимит 1GB)
log_file = os.path.join(logs_dir, "nano_banana.log")
# 1GB = 1024 * 1024 * 1024 байт, но для удобства используем 1000MB
max_bytes = 1000 * 1024 * 1024  # 1GB
backup_count = 5  # Количество резервных файлов

# Создаем ротирующий handler
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=max_bytes,
    backupCount=backup_count,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))

# Консольный handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
))

# Настройка root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

# Глобальный сервис MinIO для фоновых задач
minio_background = MinioService()

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
    error_data = {
        "type": "validation_error",
        "method": request.method,
        "url": str(request.url),
        "errors": exc.errors(),
        "path": str(request.url.path),
        "query_params": dict(request.query_params),
    }
    
    try:
        body = await request.body()
        if body:
            error_data["request_body"] = body.decode('utf-8', errors='ignore')[:1000]  # Ограничиваем размер
    except:
        pass
    
    logger.error(f"[VALIDATION] Ошибка валидации для {request.method} {request.url}")
    logger.error(f"[VALIDATION] Детали ошибки: {exc.errors()}")
    
    # Сохраняем в файл ошибок
    save_error_to_file(error_data)
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()}
    )

# Глобальный обработчик всех исключений
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Глобальный обработчик всех исключений"""
    error_data = {
        "type": "unhandled_exception",
        "method": request.method,
        "url": str(request.url),
        "error": str(exc),
        "error_type": type(exc).__name__,
        "path": str(request.url.path),
    }
    
    logger.error(f"[GLOBAL_ERROR] Необработанное исключение: {exc}", exc_info=True)
    
    # Сохраняем в файл ошибок
    save_error_to_file(error_data)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Внутренняя ошибка сервера"}
    )

# Фоновая задача автоочистки старых генераций и связанных файлов
async def auto_cleanup_task():
    """
    Периодически (раз в сутки) удаляет генерации и файлы старше 7 дней.
    """
    # Небольшая задержка после старта приложения, чтобы всё инициализировалось
    await asyncio.sleep(60)
    retention_days = 7

    while True:
        try:
            cutoff = datetime.utcnow() - timedelta(days=retention_days)
            deleted_generations = 0
            deleted_files: List[str] = []

            with db_service.get_session() as session:
                old_generations: List[Generation] = (
                    session.query(Generation)
                    .filter(Generation.created_at < cutoff)
                    .all()
                )

                if old_generations:
                    logger.info(
                        f"[AUTO_CLEANUP] Найдено {len(old_generations)} генераций "
                        f"старше {retention_days} дней для автоочистки"
                    )

                for gen in old_generations:
                    # Удаляем результат из MinIO
                    if gen.result_path:
                        if minio_background.delete_image(gen.result_path):
                            deleted_files.append(gen.result_path)

                    # Удаляем референсы из MinIO по URL, если они больше нигде не используются
                    if gen.generation_metadata:
                        ref_urls = gen.generation_metadata.get("reference_image_urls") or []
                        for url in ref_urls:
                            if not url:
                                continue

                            # Проверяем использование в других генерациях
                            other_gens: List[Generation] = (
                                session.query(Generation)
                                .filter(Generation.id != gen.id)
                                .filter(Generation.generation_metadata.isnot(None))
                                .all()
                            )
                            url_used_elsewhere = False
                            for other in other_gens:
                                other_urls = []
                                if other.generation_metadata:
                                    other_urls = other.generation_metadata.get("reference_image_urls") or []
                                if url in other_urls:
                                    url_used_elsewhere = True
                                    break

                            if url_used_elsewhere:
                                continue

                            marker = f"/{app_settings.MINIO_BUCKET}/"
                            idx = url.find(marker)
                            if idx == -1:
                                continue
                            path = url[idx + len(marker) :]

                            if path and minio_background.delete_image(path):
                                deleted_files.append(path)

                    session.delete(gen)
                    deleted_generations += 1

                session.commit()

            if deleted_generations or deleted_files:
                logger.info(
                    f"[AUTO_CLEANUP] Автоочистка завершена: "
                    f"удалено генераций={deleted_generations}, файлов в MinIO={len(deleted_files)}"
                )
        except Exception as e:
            logger.error(f"[AUTO_CLEANUP] Ошибка автоочистки: {e}", exc_info=True)

        # Ждём сутки до следующего запуска
        await asyncio.sleep(24 * 60 * 60)


# Инициализация БД и запуск фоновых задач при старте
@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске приложения"""
    try:
        db_service.create_tables()
        logger.info("[STARTUP] База данных инициализирована")
    except Exception as e:
        logger.error(f"[STARTUP] Ошибка инициализации БД: {e}")
    
    # Запускаем фоновую задачу автоочистки
    try:
        asyncio.create_task(auto_cleanup_task())
        logger.info("[STARTUP] Фоновая задача автоочистки старых генераций запущена")
    except Exception as e:
        logger.error(f"[STARTUP] Не удалось запустить фоновую задачу автоочистки: {e}", exc_info=True)

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

