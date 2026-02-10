"""
Роутер для генерации изображений через Nano Banana Pro (Replicate API)
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Optional, List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from starlette.requests import Request
from datetime import datetime, timedelta
import logging
import uuid
from app.models.schemas import ImageGenerationRequest, ImageGenerationResponse, ImageResponse
from app.services.ReplicateService import ReplicateService
from app.services.MinioService import MinioService
from app.services.DBService import db_service
from app.services.AuthService import auth_service
from app.models.base import Generation, User
from app.config import settings
from app.models.token import TokenPayload

logger = logging.getLogger(__name__)

# Глобальный пул воркеров для обработки генераций
executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)

router = APIRouter(prefix="/images", tags=["images"])
minio = MinioService()


def _extract_minio_path_from_url(url: str, bucket: str) -> Optional[str]:
    """
    Вспомогательная функция: из публичного URL MinIO достает путь объекта внутри бакета.
    Ожидаемый формат:
      {PUBLIC_URL}/{bucket}/{object_path}
    Возвращает object_path или None, если разобрать не удалось.
    """
    try:
        if not url:
            return None

        # Ищем подстроку "/{bucket}/"
        marker = f"/{bucket}/"
        idx = url.find(marker)
        if idx == -1:
            return None
        return url[idx + len(marker) :]
    except Exception:
        return None

def get_user_replicate_key(user_id: int, api_key_from_request: Optional[str] = None) -> str:
    """
    Получает API ключ Replicate из запроса пользователя.
    ВАЖНО: Ключи пользователей НЕ сохраняются в БД для безопасности.
    Каждый пользователь должен использовать свой ключ.
    """
    # Используем только ключ из запроса - никаких fallback на глобальный ключ
    if not api_key_from_request or not api_key_from_request.strip():
        raise ValueError("API ключ Replicate не указан. Пожалуйста, введите свой ключ Replicate API в настройках.")
    return api_key_from_request.strip()

def process_generation_async(generation_id: int, user_id: int, request_data: dict):
    """Асинхронная обработка генерации"""
    try:
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if not generation:
                logger.error(f"[GENERATION] Генерация {generation_id} не найдена")
                return
            
            # Обновляем статус на running
            generation.status = "running"
            session.commit()
            
            # Получаем API ключ из request_data (передан в запросе)
            # ВАЖНО: Ключи пользователей НЕ сохраняются в БД для безопасности
            api_key_from_request = request_data.get('api_key')
            logger.info(f"[GENERATION] В process_generation_async: ключ из запроса: {'передан' if api_key_from_request else 'не передан'}")
            if not api_key_from_request or not api_key_from_request.strip():
                raise ValueError("API ключ Replicate не указан. Пожалуйста, введите свой ключ Replicate API в настройках.")
            api_key = get_user_replicate_key(user_id, api_key_from_request)
            
            # Создаем сервис Replicate и генерируем изображение
            # Обрабатываем ошибки аутентификации и другие ошибки
            try:
                replicate_service = ReplicateService(api_token=api_key)
            except Exception as init_error:
                error_msg = f"Ошибка инициализации Replicate клиента: {str(init_error)}"
                logger.error(f"[GENERATION] {error_msg}")
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = error_msg
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()
                logger.error(f"[GENERATION] Генерация {generation_id} завершена с ошибкой инициализации: {error_msg}")
                return
            
            try:
                # Генерируем изображение
                result = replicate_service.generate_image(
                    prompt=request_data['prompt'],
                    negative_prompt=request_data.get('negative_prompt'),
                    resolution=request_data.get('resolution', '1K'),
                    aspect_ratio=request_data.get('aspect_ratio', '1:1'),
                    guidance_scale=request_data.get('guidance_scale', 7.5),
                    num_inference_steps=request_data.get('num_inference_steps', 50),
                    seed=request_data.get('seed'),
                    reference_images=request_data.get('reference_images')
                )
            except Exception as gen_error:
                # Ошибка при генерации (например, неправильный API ключ, таймаут и т.д.)
                # Улучшенное извлечение деталей ошибки
                error_msg = str(gen_error)
                
                # Если это специфичная ошибка Replicate, извлекаем больше деталей
                if hasattr(gen_error, 'message'):
                    error_msg = str(gen_error.message)
                elif hasattr(gen_error, 'args') and len(gen_error.args) > 0:
                    error_msg = str(gen_error.args[0])
                
                # Добавляем префикс для ясности
                full_error_msg = f"Ошибка генерации через Replicate API: {error_msg}"
                
                logger.error(f"[GENERATION] {full_error_msg}", exc_info=True)
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = full_error_msg
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()
                logger.error(f"[GENERATION] Генерация {generation_id} завершена с ошибкой генерации: {full_error_msg}")
                return
            
            if result['success']:
                # Логируем что получили от ReplicateService
                logger.info(f"[GENERATION] Результат от ReplicateService: image_url={'есть' if result.get('image_url') else 'отсутствует'}, image_data={'есть' if result.get('image_data') else 'отсутствует'}")
                # Сохраняем в MinIO если есть данные
                if result['image_data']:
                    try:
                        # Проверяем размер изображения перед сохранением
                        image_size = len(result['image_data'])
                        logger.info(f"[GENERATION] Размер изображения: {image_size} байт")
                        
                        if image_size < 1024:  # Меньше 1KB - подозрительно
                            logger.warning(f"[GENERATION] Подозрительно маленький размер изображения: {image_size} байт")
                            # Проверяем что это действительно изображение
                            try:
                                from PIL import Image as PILImage
                                import io as io_module
                                img = PILImage.open(io_module.BytesIO(result['image_data']))
                                img.verify()
                                img = PILImage.open(io_module.BytesIO(result['image_data']))  # Пересоздаем после verify
                                logger.info(f"[GENERATION] Изображение валидно: {img.format}, размер: {img.size}")
                                # Если изображение валидно, но маленькое - возможно это миниатюра, продолжаем
                            except Exception as img_error:
                                logger.error(f"[GENERATION] Данные не являются валидным изображением: {img_error}")
                                # Если не валидное изображение, пробуем загрузить полное изображение по URL от Replicate
                                image_url = result.get('image_url')
                                logger.info(f"[GENERATION] Проверка URL от Replicate: {image_url[:100] if image_url else 'URL отсутствует'}...")
                                if image_url:
                                    # Пробуем загрузить полное изображение по URL и сохранить в MinIO
                                    try:
                                        import requests as req_module
                                        logger.info(f"[GENERATION] Загрузка полного изображения по URL от Replicate: {image_url[:100]}...")
                                        img_response = req_module.get(image_url, timeout=30)
                                        if img_response.status_code == 200:
                                            full_image_data = img_response.content
                                            logger.info(f"[GENERATION] Полное изображение загружено, размер: {len(full_image_data)} байт")
                                            
                                            # Проверяем, что это валидное изображение
                                            try:
                                                from PIL import Image as PILImage
                                                import io as io_module
                                                img = PILImage.open(io_module.BytesIO(full_image_data))
                                                img.verify()
                                                img = PILImage.open(io_module.BytesIO(full_image_data))
                                                logger.info(f"[GENERATION] Полное изображение валидно: {img.format}, размер: {img.size}")
                                                
                                                # Сохраняем полное изображение в MinIO
                                                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
                                                logger.info(f"[GENERATION] Сохранение полного изображения в MinIO: {filename}")
                                                upload_result = minio.upload_image(
                                                    full_image_data,
                                                    filename,
                                                    "image/jpeg"
                                                )
                                                generation.result_url = upload_result['url']
                                                generation.result_path = upload_result['path']
                                                logger.info(f"[GENERATION] Полное изображение сохранено в MinIO, URL: {generation.result_url[:100]}...")
                                                generation.status = "completed"
                                                generation.completed_at = datetime.utcnow()
                                                session.commit()
                                                logger.info(f"[GENERATION] Генерация {generation.id} завершена с полным изображением из MinIO")
                                                return
                                            except Exception as full_img_error:
                                                logger.error(f"[GENERATION] Полное изображение также невалидно: {full_img_error}")
                                                # Используем URL от Replicate как fallback
                                                generation.result_url = image_url
                                                logger.warning(f"[GENERATION] Используется URL от Replicate как fallback: {generation.result_url[:100]}...")
                                                generation.status = "completed"
                                                generation.completed_at = datetime.utcnow()
                                                session.commit()
                                                logger.info(f"[GENERATION] Генерация {generation.id} завершена с URL от Replicate")
                                                return
                                        else:
                                            logger.warning(f"[GENERATION] Не удалось загрузить полное изображение, статус: {img_response.status_code}")
                                            # Используем URL от Replicate как fallback
                                            generation.result_url = image_url
                                            logger.warning(f"[GENERATION] Используется URL от Replicate как fallback: {generation.result_url[:100]}...")
                                            generation.status = "completed"
                                            generation.completed_at = datetime.utcnow()
                                            session.commit()
                                            logger.info(f"[GENERATION] Генерация {generation.id} завершена с URL от Replicate")
                                            return
                                    except Exception as download_error:
                                        logger.error(f"[GENERATION] Ошибка загрузки полного изображения: {download_error}")
                                        # Используем URL от Replicate как fallback
                                        generation.result_url = image_url
                                        logger.warning(f"[GENERATION] Используется URL от Replicate как fallback: {generation.result_url[:100]}...")
                                        generation.status = "completed"
                                        generation.completed_at = datetime.utcnow()
                                        session.commit()
                                        logger.info(f"[GENERATION] Генерация {generation.id} завершена с URL от Replicate")
                                        return
                                else:
                                    # Нет валидного изображения и нет URL - ошибка
                                    error_msg = f"Получены невалидные данные изображения: {image_size} байт, URL отсутствует"
                                    logger.error(f"[GENERATION] {error_msg}")
                                    generation.status = "failed"
                                    generation.completed_at = datetime.utcnow()
                                    if not generation.generation_metadata:
                                        generation.generation_metadata = {}
                                    generation.generation_metadata['error'] = error_msg
                                    # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                                    from sqlalchemy.orm.attributes import flag_modified
                                    flag_modified(generation, "generation_metadata")
                                    session.commit()
                                    logger.error(f"[GENERATION] Генерация {generation.id} завершена с ошибкой: {error_msg}")
                                    return
                        
                        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
                        logger.info(f"[GENERATION] Сохранение изображения в MinIO: {filename}")
                        upload_result = minio.upload_image(
                            result['image_data'],
                            filename,
                            "image/jpeg"
                        )
                        generation.result_url = upload_result['url']
                        generation.result_path = upload_result['path']
                        logger.info(f"[GENERATION] Изображение сохранено, URL: {generation.result_url[:100]}...")
                    except Exception as e:
                        logger.error(f"[GENERATION] Ошибка сохранения в MinIO: {e}", exc_info=True)
                        # Если не удалось сохранить в MinIO, используем URL от Replicate
                        if result.get('image_url'):
                            generation.result_url = result['image_url']
                            logger.warning(f"[GENERATION] Используется URL от Replicate: {generation.result_url}")
                        else:
                            raise
                elif result['image_url']:
                    generation.result_url = result['image_url']
                    logger.info(f"[GENERATION] Используется URL от Replicate: {generation.result_url}")
                
                generation.status = "completed"
                generation.completed_at = datetime.utcnow()
            else:
                # Генерация не удалась - сохраняем ошибку
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                # Сохраняем ошибку в generation_metadata
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                
                # Извлекаем ошибку из result
                error_message = result.get('error')
                
                # Если ошибка не указана или пустая, проверяем другие возможные поля
                if not error_message or (isinstance(error_message, str) and error_message.strip() == ''):
                    error_message = result.get('message') or result.get('detail') or result.get('error_message')
                
                # Если всё ещё нет ошибки, используем дефолтное сообщение
                if not error_message or (isinstance(error_message, str) and error_message.strip() == ''):
                    error_message = 'Неизвестная ошибка генерации'
                    logger.warning(f"[GENERATION] Генерация {generation_id} завершена с ошибкой, но error_message отсутствует в result. Result keys: {list(result.keys())}")
                
                # Убеждаемся что error_message - строка
                if not isinstance(error_message, str):
                    error_message = str(error_message)
                
                # Обрезаем слишком длинные сообщения об ошибках (максимум 2000 символов)
                if len(error_message) > 2000:
                    error_message = error_message[:2000] + "... (сообщение обрезано)"
                
                generation.generation_metadata['error'] = error_message
                
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                
                logger.error(f"[GENERATION] Генерация {generation_id} завершена с ошибкой. Сохраняем error_message: {error_message[:200]}...")
                logger.info(f"[GENERATION] generation_metadata перед commit: {generation.generation_metadata}")
                
                # Сохраняем ошибку в файл
                from app.services.ErrorLogger import save_error_to_file
                error_data = {
                    "type": "generation_error",
                    "generation_id": generation_id,
                    "user_id": user_id,
                    "prompt": request_data.get('prompt'),
                    "error": error_message,
                    "status": "failed"
                }
                save_error_to_file(error_data)
            
            session.commit()
            logger.info(f"[GENERATION] Генерация {generation_id} завершена со статусом {generation.status}")
            
            # Проверяем что error_message сохранился
            if generation.status == 'failed':
                session.refresh(generation)
                saved_error = generation.generation_metadata.get('error') if generation.generation_metadata else None
                logger.info(f"[GENERATION] Проверка сохранения error_message для генерации {generation_id}: {saved_error[:200] if saved_error else 'НЕ СОХРАНЕНО!'}...")
            
    except Exception as e:
        logger.error(f"[GENERATION] Ошибка обработки генерации {generation_id}: {e}", exc_info=True)
        
        # Сохраняем ошибку в файл
        from app.services.ErrorLogger import save_error_to_file
        error_data = {
            "type": "generation_exception",
            "generation_id": generation_id,
            "user_id": user_id,
            "error": str(e),
            "error_type": type(e).__name__,
        }
        save_error_to_file(error_data)
        
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if generation:
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = str(e)
                # ВАЖНО: Уведомляем SQLAlchemy об изменении JSON поля
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(generation, "generation_metadata")
                session.commit()

@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Генерация изображения через Nano Banana Pro
    
    Требует API ключ Replicate (либо глобальный, либо пользовательский)
    """
    try:
        # Получаем API ключ из запроса (обязательно)
        # ВАЖНО: Ключи пользователей НЕ сохраняются в БД для безопасности
        # Каждый пользователь должен использовать свой ключ
        logger.info(f"[GENERATION] API ключ из запроса: {'передан' if request.api_key else 'не передан'}")
        if not request.api_key or not request.api_key.strip():
            raise HTTPException(
                status_code=400,
                detail="API ключ Replicate не указан. Пожалуйста, введите свой ключ Replicate API в настройках."
            )
        api_key = get_user_replicate_key(user.user_id, request.api_key)
        
        # Проверяем лимиты активных генераций по API ключу
        # Создаем хеш API ключа для группировки (первые 8 символов для идентификации)
        api_key_hash = api_key[:8] if len(api_key) >= 8 else api_key
        with db_service.get_session() as session:
            # Подсчитываем активные генерации для этого API ключа
            # Используем generation_metadata для хранения хеша ключа (безопасно, не храним сам ключ)
            active_generations = session.query(Generation).filter(
                Generation.user_id == user.user_id,
                Generation.status.in_(["pending", "running"])
            ).all()
            
            # Фильтруем по API ключу через metadata (если храним хеш)
            # Или просто считаем все активные генерации пользователя
            # Для простоты считаем все активные генерации пользователя
            active_count = len(active_generations)
            max_concurrent = settings.MAX_CONCURRENT_GENERATIONS
            
            if active_count >= max_concurrent:
                raise HTTPException(
                    status_code=429,
                    detail=f"Достигнут лимит одновременных генераций ({max_concurrent}). Дождитесь завершения текущих генераций."
                )
            
            logger.info(f"[GENERATION] Активных генераций для пользователя {user.user_id}: {active_count}/{max_concurrent}")
        
        # Создаем запись в БД
        with db_service.get_session() as session:
            # Сначала создаем запись генерации для получения ID
            generation = Generation(
                user_id=user.user_id,
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                generation_mode=request.generation_mode,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                guidance_scale=request.guidance_scale,
                num_inference_steps=request.num_inference_steps,
                seed=request.seed,
                status="pending",
                generation_metadata={}
            )
            session.add(generation)
            session.commit()
            session.refresh(generation)
            
            generation_id = generation.id
            logger.info(f"[GENERATION] Генерация {generation_id} создана в БД для пользователя {user.user_id}")
            
            # Теперь сохраняем референсные изображения в MinIO и получаем их URL
            reference_image_urls = []
            if request.reference_images:
                import base64
                for idx, ref_img_data in enumerate(request.reference_images):
                    try:
                        # Если это base64 data URL, извлекаем данные
                        if ref_img_data.startswith('data:image'):
                            # Парсим data URL: data:image/jpeg;base64,/9j/4AAQ...
                            header, base64_data = ref_img_data.split(',', 1)
                            mime_type = header.split(';')[0].split(':')[1] if ':' in header else 'image/jpeg'
                            image_bytes = base64.b64decode(base64_data)
                            
                            # Определяем расширение файла
                            ext = 'jpg'
                            if 'png' in mime_type:
                                ext = 'png'
                            elif 'webp' in mime_type:
                                ext = 'webp'
                            
                            # Валидация формата изображения через PIL (только проверка, без изменения)
                            try:
                                from PIL import Image as PILImage
                                import io as image_io
                                img = PILImage.open(image_io.BytesIO(image_bytes))
                                img.verify()  # Проверяем что это валидное изображение
                                img = PILImage.open(image_io.BytesIO(image_bytes))  # Пересоздаем после verify
                                
                                # Проверяем что изображение не слишком большое (максимум 8192x8192 для валидации)
                                MAX_DIMENSION_VALIDATION = 8192
                                if img.width > MAX_DIMENSION_VALIDATION or img.height > MAX_DIMENSION_VALIDATION:
                                    error_msg = f"Референс {idx + 1} слишком большой ({img.width}x{img.height}). Максимальный размер: {MAX_DIMENSION_VALIDATION}x{MAX_DIMENSION_VALIDATION}"
                                    logger.error(f"[GENERATION] {error_msg}")
                                    raise ValueError(error_msg)
                                
                                # Проверяем размер файла (максимум 20MB для сохранения в MinIO)
                                MAX_REF_SIZE = 20 * 1024 * 1024  # 20MB
                                if len(image_bytes) > MAX_REF_SIZE:
                                    error_msg = f"Референс {idx + 1} слишком большой ({len(image_bytes) / 1024 / 1024:.1f}MB). Максимальный размер: {MAX_REF_SIZE / 1024 / 1024}MB"
                                    logger.error(f"[GENERATION] {error_msg}")
                                    raise ValueError(error_msg)
                                
                            except ValueError:
                                raise  # Пробрасываем ValueError дальше
                            except Exception as img_error:
                                error_msg = f"Референс {idx + 1} не является валидным изображением: {str(img_error)}"
                                logger.error(f"[GENERATION] {error_msg}")
                                raise ValueError(error_msg)
                            
                            # Укороченное имя файла (только timestamp + короткий UUID)
                            # Формат: ref_YYYYMMDD_HHMMSS_XXXX.ext (где XXXX - первые 4 символа UUID)
                            ref_filename = f"references/ref_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}.{ext}"
                            
                            # ВАЖНО: Сохраняем ОРИГИНАЛЬНОЕ качество в MinIO (без обработки)
                            # Оптимизация будет происходить только при отправке в Replicate API
                            upload_result = minio.upload_image(
                                image_bytes,
                                ref_filename,
                                mime_type
                            )
                            reference_image_urls.append(upload_result['url'])
                            logger.info(f"[GENERATION] Референс {idx + 1} сохранен в MinIO: {upload_result['url'][:100]}...")
                        else:
                            # Если это уже URL, сохраняем как есть
                            reference_image_urls.append(ref_img_data)
                    except Exception as e:
                        logger.error(f"[GENERATION] Ошибка сохранения референса {idx + 1}: {e}", exc_info=True)
                        # В случае ошибки сохраняем оригинальный data URL как fallback
                        reference_image_urls.append(ref_img_data)
                
                # Обновляем generation_metadata с URL референсов
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['reference_images_count'] = len(request.reference_images)
                generation.generation_metadata['reference_image_urls'] = reference_image_urls
                session.commit()
                logger.info(f"[GENERATION] Референсы сохранены для генерации {generation_id}: {len(reference_image_urls)} URL")
        
        # Запускаем асинхронную обработку
        request_data = request.dict()
        executor.submit(process_generation_async, generation_id, user.user_id, request_data)
        
        logger.info(f"[GENERATION] Задача {generation_id} добавлена в очередь пользователем {user.user_id}")
        
        return ImageGenerationResponse(
            status="pending",
            image_id=generation_id,
            message="Генерация добавлена в очередь"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GENERATION] Ошибка создания задачи: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка создания задачи генерации: {str(e)}")

@router.get("/list", response_model=list[ImageResponse])
async def list_generations(
    request: Request,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Список генераций пользователя"""
    try:
        # Получаем параметры из query string напрямую, чтобы избежать проблем с валидацией FastAPI
        query_params = request.query_params
        limit_str = query_params.get("limit")
        offset_str = query_params.get("offset")
        
        # Валидация и нормализация параметров
        try:
            if limit_str is None or limit_str == "":
                limit_val = 50
            else:
                limit_val = int(limit_str)
                if limit_val < 1 or limit_val > 100:
                    limit_val = 50
        except (ValueError, TypeError):
            limit_val = 50
        
        try:
            if offset_str is None or offset_str == "":
                offset_val = 0
            else:
                offset_val = int(offset_str)
                if offset_val < 0:
                    offset_val = 0
        except (ValueError, TypeError):
            offset_val = 0
        
        logger.info(f"[LIST] Запрос списка генераций для пользователя {user.user_id}, limit={limit_val}, offset={offset_val}")
        with db_service.get_session() as session:
            # Проверяем, что пользователь существует
            db_user = session.query(User).filter(User.id == user.user_id).first()
            if not db_user:
                logger.error(f"[LIST] Пользователь {user.user_id} не найден в БД")
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            
            # Получаем общее количество генераций пользователя
            total_count = session.query(Generation).filter(Generation.user_id == user.user_id).count()
            
            # Получаем все генерации пользователя
            all_generations = session.query(Generation).filter(
                Generation.user_id == user.user_id
            ).order_by(Generation.created_at.desc()).all()
            
            logger.info(f"[LIST] Всего генераций для пользователя {user.user_id}: {len(all_generations)}")
            
            # Применяем limit и offset
            generations = all_generations[offset_val:offset_val+limit_val]
            
            logger.info(f"[LIST] Возвращаем {len(generations)} генераций (limit={limit_val}, offset={offset_val})")
            
            result = []
            for gen in generations:
                # Извлекаем error_message из generation_metadata
                # Для старых генераций (до добавления error_message) будет None
                error_msg = None
                if gen.generation_metadata:
                    error_msg = gen.generation_metadata.get('error')
                    # Логируем только для failed генераций без error_message (проблема!)
                    if gen.status == 'failed' and not error_msg:
                        logger.warning(f"[LIST] Генерация {gen.id} имеет статус 'failed', но error_message отсутствует в generation_metadata: {gen.generation_metadata}")
                elif gen.status == 'failed':
                    logger.warning(f"[LIST] Генерация {gen.id} имеет статус 'failed', но generation_metadata отсутствует")
                
                result.append(ImageResponse(
                    id=gen.id,
                    user_id=gen.user_id,
                    prompt=gen.prompt,
                    negative_prompt=gen.negative_prompt,
                    generation_mode=gen.generation_mode,
                    resolution=gen.resolution,
                    aspect_ratio=gen.aspect_ratio,
                    result_url=gen.result_url,
                    status=gen.status,
                    created_at=gen.created_at,
                    error_message=error_msg  # None для старых генераций без ошибок
                ))
            
            # Логируем только активные процессы (running/pending), чтобы не засорять логи
            running_count = sum(1 for resp in result if resp.status == 'running')
            pending_count = sum(1 for resp in result if resp.status == 'pending')
            if running_count or pending_count:
                logger.info(
                    f"[LIST] Активные генерации пользователя {user.user_id}: "
                    f"выполняется={running_count}, в очереди={pending_count}"
                )
            
            # Возвращаем результат с метаданными
            from fastapi.responses import JSONResponse
            import json
            
            # Сериализуем генерации с правильной обработкой datetime
            generations_data = []
            for gen in result:
                gen_dict = gen.dict()
                # Преобразуем datetime в строки для JSON сериализации
                if 'created_at' in gen_dict and gen_dict['created_at']:
                    gen_dict['created_at'] = gen_dict['created_at'].isoformat() if hasattr(gen_dict['created_at'], 'isoformat') else str(gen_dict['created_at'])
                if 'updated_at' in gen_dict and gen_dict.get('updated_at'):
                    gen_dict['updated_at'] = gen_dict['updated_at'].isoformat() if hasattr(gen_dict['updated_at'], 'isoformat') else str(gen_dict['updated_at'])
                if 'completed_at' in gen_dict and gen_dict.get('completed_at'):
                    gen_dict['completed_at'] = gen_dict['completed_at'].isoformat() if hasattr(gen_dict['completed_at'], 'isoformat') else str(gen_dict['completed_at'])
                # Убрали избыточное логирование error_message
                generations_data.append(gen_dict)
            
            return JSONResponse(content={
                "generations": generations_data,
                "meta": {
                    "total": total_count,
                    "shown": len(result),
                    "limit": limit_val,
                    "offset": offset_val,
                    "storage_info": {
                        "retention_days": 7,
                        "message": "Изображения хранятся 7 дней, затем автоматически удаляются"
                    }
                }
            })
    except Exception as e:
        logger.error(f"[LIST] Ошибка получения списка генераций: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка получения списка генераций: {str(e)}")

@router.get("/{generation_id}", response_model=dict)
async def get_generation_full(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Получение полных данных генерации для редактирования"""
    with db_service.get_session() as session:
        generation = session.query(Generation).filter(
            Generation.id == generation_id,
            Generation.user_id == user.user_id
        ).first()
        
        if not generation:
            raise HTTPException(status_code=404, detail="Генерация не найдена")
        
        return {
            "id": generation.id,
            "prompt": generation.prompt,
            "negative_prompt": generation.negative_prompt,
            "generation_mode": generation.generation_mode,
            "resolution": generation.resolution,
            "aspect_ratio": generation.aspect_ratio,
            "guidance_scale": generation.guidance_scale,
            "num_inference_steps": generation.num_inference_steps,
            "seed": generation.seed,
            "reference_images": generation.generation_metadata.get("reference_image_urls", []) if generation.generation_metadata else [],
            "result_url": generation.result_url,
            "status": generation.status,
            "error_message": generation.generation_metadata.get('error') if generation.generation_metadata else None
        }

@router.delete("/{generation_id}")
async def delete_generation(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """Удаление генерации"""
    with db_service.get_session() as session:
        generation = session.query(Generation).filter(
            Generation.id == generation_id,
            Generation.user_id == user.user_id
        ).first()
        
        if not generation:
            raise HTTPException(status_code=404, detail="Генерация не найдена")
        
        # Удаляем из MinIO результат, если есть
        if generation.result_path:
            minio.delete_image(generation.result_path)

        session.delete(generation)
        session.commit()

        return {"message": "Генерация удалена"}


@router.post("/cleanup")
async def cleanup_old_generations(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Очистка генераций и связанных изображений старше 7 дней.

    Эндпоинт защищен: выполнять может только админ (is_admin=True).
    Предполагается, что его будет дергать крон или ручной вызов админа.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    retention_days = 7
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    deleted_count = 0
    deleted_files: List[str] = []

    from app.config import settings as app_settings

    with db_service.get_session() as session:
        old_generations: List[Generation] = (
            session.query(Generation)
            .filter(Generation.created_at < cutoff)
            .all()
        )

        logger.info(
            f"[CLEANUP] Найдено {len(old_generations)} генераций старше {retention_days} дней для удаления"
        )

        for gen in old_generations:
            # Удаляем результат из MinIO
            if gen.result_path:
                if minio.delete_image(gen.result_path):
                    deleted_files.append(gen.result_path)
            # Удаляем референсы из MinIO (по сохраненным публичным URL),
            # только если этот URL не используется ни в одной другой генерации.
            if gen.generation_metadata:
                ref_urls: List[str] = gen.generation_metadata.get("reference_image_urls") or []
                for url in ref_urls:
                    if not url:
                        continue
                    # Проверяем, есть ли другие генерации (кроме текущей),
                    # у которых в metadata присутствует этот же URL
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

                    path = _extract_minio_path_from_url(url, app_settings.MINIO_BUCKET)
                    if path and minio.delete_image(path):
                        deleted_files.append(path)

            session.delete(gen)
            deleted_count += 1

        session.commit()

    logger.info(
        f"[CLEANUP] Удалено генераций: {deleted_count}, файлов в MinIO: {len(deleted_files)}"
    )

    return {
        "deleted_generations": deleted_count,
        "deleted_files": deleted_files,
        "retention_days": retention_days,
    }

