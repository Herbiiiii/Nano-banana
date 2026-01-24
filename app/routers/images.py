"""
Роутер для генерации изображений через Nano Banana Pro (Replicate API)
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from starlette.requests import Request
from datetime import datetime
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

def get_user_replicate_key(user_id: int, api_key_from_request: Optional[str] = None) -> str:
    """
    Получает API ключ Replicate из запроса пользователя или использует глобальный.
    ВАЖНО: Ключи пользователей НЕ сохраняются в БД для безопасности.
    """
    # Используем ключ из запроса если он передан
    if api_key_from_request:
        return api_key_from_request
    # Используем глобальный ключ если у пользователя нет своего
    if not settings.REPLICATE_API_TOKEN:
        raise ValueError("API ключ Replicate не настроен. Пожалуйста, укажите свой ключ в запросе или настройте глобальный ключ.")
    return settings.REPLICATE_API_TOKEN

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
            
            # Получаем API ключ из request_data (передан в запросе) или используем глобальный
            # ВАЖНО: Ключи пользователей НЕ сохраняются в БД для безопасности
            api_key_from_request = request_data.get('api_key')
            api_key = get_user_replicate_key(user_id, api_key_from_request)
            if not api_key:
                raise ValueError("API ключ Replicate не найден. Укажите ключ в запросе или используйте глобальный ключ.")
            
            # Создаем сервис Replicate
            replicate_service = ReplicateService(api_token=api_key)
            
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
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                # Сохраняем ошибку в generation_metadata
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = result['error']
            
            session.commit()
            logger.info(f"[GENERATION] Генерация {generation_id} завершена со статусом {generation.status}")
            
    except Exception as e:
        logger.error(f"[GENERATION] Ошибка обработки генерации {generation_id}: {e}", exc_info=True)
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if generation:
                generation.status = "failed"
                generation.completed_at = datetime.utcnow()
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata['error'] = str(e)
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
        # Получаем API ключ из запроса или используем глобальный
        # ВАЖНО: Ключи пользователей НЕ сохраняются в БД для безопасности
        logger.info(f"[GENERATION] API ключ из запроса: {'передан' if request.api_key else 'не передан'}, глобальный ключ: {'настроен' if settings.REPLICATE_API_TOKEN else 'не настроен'}")
        api_key = get_user_replicate_key(user.user_id, request.api_key)
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="Replicate API ключ не указан. Пожалуйста, укажите свой ключ в запросе или используйте глобальный ключ (если настроен)."
            )
        
        # Создаем запись в БД
        with db_service.get_session() as session:
            # Сохраняем URL референсных изображений для последующего редактирования
            reference_image_urls = []
            if request.reference_images:
                # Если это base64, сохраняем как есть (для последующего использования)
                reference_image_urls = request.reference_images
            
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
                generation_metadata={
                    "reference_images_count": len(request.reference_images) if request.reference_images else 0,
                    "reference_image_urls": reference_image_urls
                }
            )
            session.add(generation)
            session.commit()
            session.refresh(generation)
            
            generation_id = generation.id
            logger.info(f"[GENERATION] Генерация {generation_id} сохранена в БД для пользователя {user.user_id}")
        
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
            
            result = [
                ImageResponse(
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
                    error_message=gen.generation_metadata.get('error') if gen.generation_metadata else None
                )
                for gen in generations
            ]
            
            # Логируем URL для отладки
            for resp in result:
                if resp.result_url:
                    logger.info(f"[LIST] Генерация {resp.id} (статус: {resp.status}): result_url={resp.result_url}")
            
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
            "status": generation.status
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
        
        # Удаляем из MinIO если есть
        if generation.result_path:
            minio.delete_image(generation.result_path)
        
        session.delete(generation)
        session.commit()
        
        return {"message": "Генерация удалена"}

