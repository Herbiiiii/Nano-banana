"""
Сервис для работы с Replicate API (Nano Banana Pro)
"""
import replicate
import requests
import io
import logging
from typing import Optional, List, Dict, Any
from PIL import Image
import time

logger = logging.getLogger(__name__)

class ReplicateService:
    """Сервис для генерации изображений через Replicate API"""
    
    MODEL_NAME = "google/nano-banana-pro"
    TIMEOUT = 600  # 10 минут
    
    # Лимиты Nano Banana Pro API для референсных изображений
    MAX_REF_DIMENSION = 2048  # Максимальный размер по большей стороне
    MAX_REF_SIZE_MB = 5  # Максимальный размер файла в MB
    
    def _optimize_image_for_api(self, image_data: bytes, ref_index: int) -> bytes:
        """
        Оптимизирует изображение для Nano Banana Pro API.
        Сохраняет оригинал в MinIO, но оптимизирует для отправки в API.
        
        Args:
            image_data: Байты изображения
            ref_index: Индекс референса (для логирования)
        
        Returns:
            bytes: Оптимизированные байты изображения
        """
        try:
            from PIL import Image as PILImage
            import io as image_io
            
            # Открываем изображение
            img = PILImage.open(image_io.BytesIO(image_data))
            
            original_size = len(image_data)
            original_dimensions = (img.width, img.height)
            
            # Проверяем размеры - если больше лимита, уменьшаем
            needs_resize = False
            if img.width > self.MAX_REF_DIMENSION or img.height > self.MAX_REF_DIMENSION:
                needs_resize = True
                logger.info(f"[REPLICATE] Референс {ref_index}: размер {img.width}x{img.height} превышает лимит {self.MAX_REF_DIMENSION}px, уменьшаем...")
                
                # Вычисляем новые размеры с сохранением пропорций
                if img.width > img.height:
                    new_width = self.MAX_REF_DIMENSION
                    new_height = int(img.height * (self.MAX_REF_DIMENSION / img.width))
                else:
                    new_height = self.MAX_REF_DIMENSION
                    new_width = int(img.width * (self.MAX_REF_DIMENSION / img.height))
                
                img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
            
            # Проверяем размер файла - если больше лимита, сжимаем
            output = image_io.BytesIO()
            max_size_bytes = self.MAX_REF_SIZE_MB * 1024 * 1024
            
            # Определяем формат
            if img.format == 'PNG':
                quality = 95
                while True:
                    output.seek(0)
                    output.truncate(0)
                    img.save(output, format='PNG', optimize=True, compress_level=6)
                    if len(output.getvalue()) <= max_size_bytes or quality <= 50:
                        break
                    # Если PNG слишком большой, конвертируем в JPEG
                    if img.mode in ('RGBA', 'LA', 'P'):
                        # Создаем белый фон для прозрачности
                        background = PILImage.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    else:
                        img = img.convert('RGB')
                    quality = 85
                    output.seek(0)
                    output.truncate(0)
                    img.save(output, format='JPEG', quality=quality, optimize=True)
                    break
            elif img.format == 'WEBP':
                quality = 85
                while True:
                    output.seek(0)
                    output.truncate(0)
                    img.save(output, format='WEBP', quality=quality, method=6)
                    if len(output.getvalue()) <= max_size_bytes or quality <= 50:
                        break
                    quality -= 5
            else:
                # JPEG или другой формат
                quality = 85
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                while True:
                    output.seek(0)
                    output.truncate(0)
                    img.save(output, format='JPEG', quality=quality, optimize=True)
                    if len(output.getvalue()) <= max_size_bytes or quality <= 50:
                        break
                    quality -= 5
            
            optimized_data = output.getvalue()
            optimized_size = len(optimized_data)
            
            if needs_resize or optimized_size < original_size * 0.9:
                logger.info(f"[REPLICATE] Референс {ref_index} оптимизирован: {original_dimensions[0]}x{original_dimensions[1]} ({original_size / 1024:.1f}KB) -> "
                          f"{img.width}x{img.height} ({optimized_size / 1024:.1f}KB)")
            
            return optimized_data
            
        except Exception as e:
            logger.warning(f"[REPLICATE] Не удалось оптимизировать референс {ref_index}: {e}. Используем оригинал.")
            return image_data  # Возвращаем оригинал если оптимизация не удалась
    
    def __init__(self, api_token: str):
        """
        Инициализация клиента Replicate
        
        Args:
            api_token: API ключ Replicate пользователя
        """
        if not api_token:
            raise ValueError("Replicate API token is required")
        self.client = replicate.Client(api_token=api_token)
        logger.info("[REPLICATE] Клиент Replicate создан")
    
    def generate_image(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        resolution: str = "1K",
        aspect_ratio: str = "1:1",
        guidance_scale: float = 7.5,
        num_inference_steps: int = 50,
        seed: Optional[int] = None,
        reference_images: Optional[List] = None
    ) -> Dict[str, Any]:
        """
        Генерирует изображение через Nano Banana Pro
        
        Returns:
            dict: {
                'success': bool,
                'image_url': str или None,
                'image_data': bytes или None,
                'error': str или None
            }
        """
        try:
            logger.info(f"[REPLICATE] Начало генерации. Промпт: {prompt[:100]}...")
            logger.info(f"[REPLICATE] Параметры: resolution={resolution}, aspect_ratio={aspect_ratio}")
            
            # Подготовка параметров
            input_params = {
                "prompt": prompt,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio
            }
            
            # Добавляем опциональные параметры
            if negative_prompt:
                input_params["negative_prompt"] = negative_prompt
            if guidance_scale != 7.5:
                input_params["guidance_scale"] = guidance_scale
            if num_inference_steps != 50:
                input_params["num_inference_steps"] = num_inference_steps
            if seed is not None:
                input_params["seed"] = int(seed)
            
            # Обработка референсных изображений
            if reference_images and len(reference_images) > 0:
                processed_images = []
                for idx, img in enumerate(reference_images[:14], 1):  # Максимум 14 изображений
                    try:
                        if isinstance(img, str):
                            # Если это base64 или URL
                            if img.startswith('data:image'):
                                # Base64 изображение
                                import base64
                                header, encoded = img.split(',', 1)
                                img_data = base64.b64decode(encoded)
                                
                                # Оптимизируем изображение для Nano Banana Pro API (если нужно)
                                img_data = self._optimize_image_for_api(img_data, idx)
                                
                                processed_images.append(io.BytesIO(img_data))
                                logger.debug(f"[REPLICATE] Референс {idx}: обработан base64 изображение")
                            elif img.startswith(('http://', 'https://')):
                                # URL изображение - загружаем и оптимизируем
                                img_response = requests.get(img, timeout=30)
                                if img_response.status_code == 200:
                                    img_data = img_response.content
                                    
                                    # Оптимизируем изображение для Nano Banana Pro API (если нужно)
                                    img_data = self._optimize_image_for_api(img_data, idx)
                                    
                                    processed_images.append(io.BytesIO(img_data))
                                    logger.debug(f"[REPLICATE] Референс {idx}: загружен с URL и оптимизирован")
                                else:
                                    logger.warning(f"[REPLICATE] Референс {idx}: не удалось загрузить с URL (статус {img_response.status_code})")
                            else:
                                # Прямой путь к файлу
                                processed_images.append(img)
                                logger.debug(f"[REPLICATE] Референс {idx}: используется файл")
                        elif hasattr(img, 'read'):
                            # Если это файлоподобный объект
                            img.seek(0)
                            img_data = img.read()
                            
                            # Оптимизируем изображение для Nano Banana Pro API (если нужно)
                            img_data = self._optimize_image_for_api(img_data, idx)
                            
                            processed_images.append(io.BytesIO(img_data))
                            logger.debug(f"[REPLICATE] Референс {idx}: обработан файлоподобный объект и оптимизирован")
                    except Exception as e:
                        logger.error(f"[REPLICATE] Ошибка обработки референса {idx}: {e}")
                        continue
                
                if processed_images:
                    input_params["image_input"] = processed_images
                    logger.info(f"[REPLICATE] Загружено {len(processed_images)} референсных изображений в порядке: 1-{len(processed_images)}")
                else:
                    logger.warning("[REPLICATE] Не удалось обработать ни одного референсного изображения")
            
            # Если aspect_ratio начинается с "user", соотношение уже вычислено на фронтенде
            # и передано как стандартное (например "16:9", "4:3" и т.д.)
            # Nano Banana Pro поддерживает только стандартные соотношения
            # Пользовательские соотношения конвертируются в ближайшее стандартное на фронтенде
            
            # Улучшение промпта для text-to-image (если нет референсов)
            if not reference_images or len(reference_images) == 0:
                # Для text-to-image всегда улучшаем промпт, чтобы модель понимала что нужно генерировать изображение
                prompt_lower = prompt.lower().strip()
                
                # Список слов, которые явно указывают на генерацию изображения
                image_generation_keywords = [
                    'generate', 'создать', 'сделать', 'сгенерируй', 'сгенерировать',
                    'изображение', 'image', 'картинка', 'picture', 'фото', 'photo',
                    'draw', 'рисовать', 'нарисовать', 'нарисуй',
                    'create', 'создай', 'создавать',
                    'design', 'дизайн', 'спроектировать',
                    'icon', 'иконка', 'favicon', 'фавикон',
                    'logo', 'логотип', 'лого'
                ]
                
                # Проверяем есть ли явные указания на генерацию изображения
                has_generation_keyword = any(keyword in prompt_lower for keyword in image_generation_keywords)
                
                # Проверяем начинается ли промпт с указания на генерацию
                starts_with_generation = any(prompt_lower.startswith(keyword) for keyword in ['generate', 'создать', 'сделать', 'сгенерируй', 'create', 'draw', 'нарисуй'])
                
                # Если нет явных указаний на генерацию изображения, добавляем префикс
                if not has_generation_keyword or not starts_with_generation:
                    # Если промпт уже начинается с "Generate" или похожего, не дублируем
                    if not prompt_lower.startswith(('generate', 'create', 'draw', 'make', 'создать', 'сделать', 'нарисовать')):
                        enhanced_prompt = f"Generate an image of {prompt}"
                        logger.info(f"[REPLICATE] Промпт улучшен для text-to-image: {enhanced_prompt[:100]}...")
                        input_params["prompt"] = enhanced_prompt
                    else:
                        # Промпт уже начинается с команды генерации, но может быть недостаточно четким
                        # Добавляем уточнение если нужно
                        if 'image' not in prompt_lower and 'изображение' not in prompt_lower and 'картинка' not in prompt_lower:
                            enhanced_prompt = f"{prompt}, high quality image"
                            logger.info(f"[REPLICATE] Промпт улучшен для text-to-image (добавлено уточнение): {enhanced_prompt[:100]}...")
                            input_params["prompt"] = enhanced_prompt
                        else:
                            input_params["prompt"] = prompt
                else:
                    input_params["prompt"] = prompt
            
            # Улучшение промпта для референсных изображений
            if reference_images and len(reference_images) > 0:
                prompt_lower = prompt.lower()
                
                # Определяем количество референсов
                num_refs = len(processed_images) if processed_images else len(reference_images)
                
                # Улучшаем промпт с указанием номеров референсов
                # Заменяем упоминания "референс 1", "реф 1", "референса 1", "реф1" и т.д. на понятные инструкции
                enhanced_prompt = prompt
                
                # Паттерны для поиска упоминаний референсов
                import re
                ref_patterns = [
                    (r'реф\s*(\d+)', r'reference image \1'),
                    (r'референс\s*(\d+)', r'reference image \1'),
                    (r'референса\s*(\d+)', r'reference image \1'),
                    (r'референсом\s*(\d+)', r'reference image \1'),
                    (r'ref\s*(\d+)', r'reference image \1'),
                ]
                
                for pattern, replacement in ref_patterns:
                    enhanced_prompt = re.sub(pattern, replacement, enhanced_prompt, flags=re.IGNORECASE)
                
                # Добавляем инструкции для работы с несколькими референсами
                if num_refs > 1:
                    ref_instructions = (
                        f"IMPORTANT: You have {num_refs} reference images. "
                        f"When the prompt mentions 'reference image 1' or 'ref 1', use the FIRST reference image. "
                        f"When it mentions 'reference image 2' or 'ref 2', use the SECOND reference image. "
                        f"And so on for reference images 3 and 4. "
                        f"Follow the prompt instructions carefully for which reference to use for which element. "
                    )
                    enhanced_prompt = ref_instructions + enhanced_prompt
                else:
                    # Для одного референса добавляем стандартные инструкции
                    if not any(phrase in prompt_lower for phrase in ["based on", "using the reference", "preserve", "reference image"]):
                        enhanced_prompt = (
                            f"STRICT INSTRUCTIONS: Use the reference image as the EXACT base. "
                            f"Preserve EVERYTHING: exact same person, identical facial features, same age, "
                            f"same gender, same body type, same pose, same clothing, same background. "
                            f"ONLY modify according to: {enhanced_prompt}."
                        )
                
                input_params["prompt"] = enhanced_prompt
                logger.info(f"[REPLICATE] Промпт улучшен для {num_refs} референсных изображений")
            
            # Вызов API
            start_time = time.time()
            logger.info("[REPLICATE] Отправка запроса в Replicate API...")
            
            output = self.client.run(self.MODEL_NAME, input=input_params)
            
            # Обработка результата
            result_data = None
            result_url = None
            original_output = output  # Сохраняем исходный объект для получения URL
            
            if hasattr(output, '__iter__') and not isinstance(output, (str, bytes)):
                # Итератор
                logger.info("[REPLICATE] Результат - итератор, получаем элементы...")
                # Пробуем получить URL из объекта итератора до получения элементов
                if hasattr(output, 'url'):
                    try:
                        if callable(getattr(output, 'url', None)):
                            result_url = output.url()
                        else:
                            result_url = str(output.url)
                        logger.info(f"[REPLICATE] URL получен из итератора: {result_url[:100] if result_url else 'URL отсутствует'}...")
                    except Exception as iter_url_error:
                        logger.debug(f"[REPLICATE] Не удалось получить URL из итератора: {iter_url_error}")
                
                # Пробуем получить URL из других атрибутов итератора
                if not result_url:
                    for attr_name in ['uri', 'path', 'href', 'link', 'source', 'file']:
                        if hasattr(output, attr_name):
                            try:
                                attr_value = getattr(output, attr_name)
                                if callable(attr_value):
                                    attr_value = attr_value()
                                attr_str = str(attr_value)
                                if attr_str.startswith(('http://', 'https://')):
                                    result_url = attr_str
                                    logger.info(f"[REPLICATE] URL получен из атрибута итератора {attr_name}: {result_url[:100]}...")
                                    break
                            except Exception as attr_error:
                                logger.debug(f"[REPLICATE] Не удалось получить URL из атрибута {attr_name}: {attr_error}")
                
                for item in output:
                    elapsed = time.time() - start_time
                    if elapsed > self.TIMEOUT:
                        raise TimeoutError(f"Таймаут генерации ({self.TIMEOUT} секунд)")
                    if item:
                        logger.info(f"[REPLICATE] Получен результат за {elapsed:.1f} сек, тип: {type(item)}")
                        # Если item - это строка URL, сохраняем её сразу
                        if isinstance(item, str) and item.startswith(('http://', 'https://')):
                            logger.info(f"[REPLICATE] Элемент итератора - строка URL: {item[:100]}...")
                            result_url = item  # Сохраняем URL сразу
                        # Если item - это bytes, но у нас уже есть URL, сохраняем его
                        elif isinstance(item, bytes) and result_url:
                            logger.info(f"[REPLICATE] Элемент итератора - bytes, URL уже сохранен: {result_url[:100]}...")
                        output = item
                        break
            else:
                elapsed = time.time() - start_time
                logger.info(f"[REPLICATE] Генерация завершена за {elapsed:.1f} сек")
            
            # Обработка результата
            logger.info(f"[REPLICATE] Тип результата: {type(output)}, значение: {str(output)[:200] if not isinstance(output, bytes) else f'bytes ({len(output)} байт)'}")
            
            if isinstance(output, bytes):
                result_data = output
                logger.info(f"[REPLICATE] Результат - bytes, размер: {len(result_data)} байт")
                # Если результат - bytes, но URL не сохранен, пробуем получить его из исходного объекта
                if not result_url:
                    logger.warning(f"[REPLICATE] Результат - bytes, но URL не сохранен. Пробуем получить URL из исходного объекта...")
                    # Пробуем получить URL из исходного объекта итератора
                    if hasattr(original_output, 'url'):
                        try:
                            if callable(getattr(original_output, 'url', None)):
                                result_url = original_output.url()
                            else:
                                result_url = str(original_output.url)
                            logger.info(f"[REPLICATE] URL получен из исходного объекта: {result_url[:100] if result_url else 'URL отсутствует'}...")
                        except Exception as orig_url_error:
                            logger.debug(f"[REPLICATE] Не удалось получить URL из исходного объекта: {orig_url_error}")
                    
                    # Пробуем получить URL из других атрибутов исходного объекта
                    if not result_url:
                        for attr_name in ['uri', 'path', 'href', 'link', 'source', 'file']:
                            if hasattr(original_output, attr_name):
                                try:
                                    attr_value = getattr(original_output, attr_name)
                                    if callable(attr_value):
                                        attr_value = attr_value()
                                    attr_str = str(attr_value)
                                    if attr_str.startswith(('http://', 'https://')):
                                        result_url = attr_str
                                        logger.info(f"[REPLICATE] URL получен из атрибута исходного объекта {attr_name}: {result_url[:100]}...")
                                        break
                                except Exception as attr_error:
                                    logger.debug(f"[REPLICATE] Не удалось получить URL из атрибута {attr_name}: {attr_error}")
            elif hasattr(output, 'url'):
                try:
                    if callable(getattr(output, 'url', None)):
                        result_url = output.url()
                    else:
                        result_url = str(output.url)
                    logger.info(f"[REPLICATE] Результат - объект с URL: {result_url[:100] if result_url else 'URL отсутствует'}...")
                except Exception as url_error:
                    logger.error(f"[REPLICATE] Ошибка получения URL из объекта: {url_error}")
                    # Пробуем получить URL другим способом
                    if hasattr(output, '__str__'):
                        url_str = str(output)
                        if url_str.startswith(('http://', 'https://')):
                            result_url = url_str
                            logger.info(f"[REPLICATE] URL получен через __str__: {result_url[:100]}...")
            elif hasattr(output, '__getitem__'):
                # Может быть словарь или объект с доступом по ключу
                try:
                    if 'url' in output:
                        result_url = str(output['url'])
                        logger.info(f"[REPLICATE] URL получен из словаря/объекта: {result_url[:100]}...")
                    elif hasattr(output, 'get') and callable(output.get):
                        result_url = output.get('url')
                        if result_url:
                            result_url = str(result_url)
                            logger.info(f"[REPLICATE] URL получен через get(): {result_url[:100]}...")
                except Exception as dict_error:
                    logger.warning(f"[REPLICATE] Не удалось получить URL из словаря/объекта: {dict_error}")
            
            # Пробуем получить URL из других возможных атрибутов (только если результат еще не обработан)
            if not result_url and not result_data:
                for attr_name in ['uri', 'path', 'href', 'link', 'source']:
                    if hasattr(output, attr_name):
                        try:
                            attr_value = getattr(output, attr_name)
                            if callable(attr_value):
                                attr_value = attr_value()
                            attr_str = str(attr_value)
                            if attr_str.startswith(('http://', 'https://')):
                                result_url = attr_str
                                logger.info(f"[REPLICATE] URL получен из атрибута {attr_name}: {result_url[:100]}...")
                                break
                        except Exception as attr_error:
                            logger.debug(f"[REPLICATE] Не удалось получить URL из атрибута {attr_name}: {attr_error}")
            
            # Обработка строки (только если результат еще не обработан как bytes)
            if not result_data and isinstance(output, str):
                if output.startswith(('http://', 'https://')):
                    result_url = output
                    logger.info(f"[REPLICATE] Результат - строка URL: {result_url[:100]}...")
                else:
                    logger.warning(f"[REPLICATE] Результат - строка, но не URL: {output[:200]}")
            
            # Обработка других типов (только если результат еще не обработан)
            if not result_data and not result_url and not isinstance(output, (bytes, str)):
                # Пробуем преобразовать в строку и проверить, не URL ли это
                try:
                    output_str = str(output)
                    if output_str.startswith(('http://', 'https://')):
                        result_url = output_str
                        logger.info(f"[REPLICATE] URL получен через str(): {result_url[:100]}...")
                    else:
                        logger.error(f"[REPLICATE] Неожиданный тип результата: {type(output)}, значение: {output_str[:200]}")
                        # Не выбрасываем ошибку, если у нас есть данные или URL
                        if not result_data and not result_url:
                            raise ValueError(f"Неожиданный тип результата: {type(output)}")
                except ValueError:
                    raise
                except Exception as e:
                    logger.error(f"[REPLICATE] Ошибка обработки результата: {e}")
                    # Не выбрасываем ошибку, если у нас есть данные или URL
                    if not result_data and not result_url:
                        raise ValueError(f"Не удалось обработать результат: {type(output)}")
            
            logger.info(f"[REPLICATE] После обработки результата: result_url={'есть' if result_url else 'отсутствует'}, result_data={'есть' if result_data else 'отсутствует'}")
            
            # Загрузка изображения если есть URL
            if result_url and not result_data:
                try:
                    logger.info(f"[REPLICATE] Загрузка изображения по URL: {result_url[:100]}...")
                    img_response = requests.get(result_url, timeout=30)
                    if img_response.status_code == 200:
                        result_data = img_response.content
                        logger.info(f"[REPLICATE] Изображение загружено, размер: {len(result_data)} байт")
                        
                        # Проверяем что это валидное изображение
                        # Сначала проверяем размер - если меньше 1KB, это подозрительно
                        if len(result_data) < 1024:
                            logger.warning(f"[REPLICATE] Подозрительно маленький размер данных: {len(result_data)} байт")
                            # Пробуем открыть через Pillow - если не получается, используем URL
                            try:
                                img = Image.open(io.BytesIO(result_data))
                                img.verify()
                                img = Image.open(io.BytesIO(result_data))  # Пересоздаем после verify
                                logger.info(f"[REPLICATE] Изображение валидно несмотря на малый размер: {img.format}, размер: {img.size}")
                            except Exception as small_img_error:
                                logger.error(f"[REPLICATE] Данные слишком маленькие и невалидны (вероятно обрезано): {small_img_error}")
                                logger.warning(f"[REPLICATE] Первые 200 байт данных (hex): {result_data[:200].hex()}")
                                # Используем URL напрямую, не сохраняем невалидные данные
                                result_data = None
                                logger.info(f"[REPLICATE] Будет использован URL напрямую: {result_url[:100]}...")
                        else:
                            # Размер нормальный, проверяем что это валидное изображение
                            try:
                                # Быстрая проверка по магическим байтам (заголовкам файлов)
                                image_signatures = {
                                    b'\xff\xd8\xff': 'JPEG',
                                    b'\x89PNG\r\n\x1a\n': 'PNG',
                                    b'GIF87a': 'GIF',
                                    b'GIF89a': 'GIF',
                                    b'RIFF': 'WEBP',  # WEBP начинается с RIFF
                                }
                                
                                is_image = False
                                detected_format = None
                                for signature, fmt in image_signatures.items():
                                    if result_data.startswith(signature):
                                        is_image = True
                                        detected_format = fmt
                                        break
                                
                                if is_image:
                                    logger.info(f"[REPLICATE] Обнаружен формат изображения по заголовку: {detected_format}")
                                
                                # Проверяем через Pillow
                                img = Image.open(io.BytesIO(result_data))
                                img.verify()
                                img = Image.open(io.BytesIO(result_data))  # Пересоздаем после verify
                                logger.info(f"[REPLICATE] Изображение валидно: {img.format}, размер: {img.size}, размер файла: {len(result_data)} байт")
                            except Exception as img_error:
                                logger.error(f"[REPLICATE] Загруженные данные не являются валидным изображением: {img_error}")
                                logger.warning(f"[REPLICATE] Первые 200 байт данных (hex): {result_data[:200].hex()}")
                                logger.warning(f"[REPLICATE] Первые 200 байт данных (text): {result_data[:200]}")
                                # Используем URL напрямую, не сохраняем невалидные данные
                                result_data = None
                                logger.info(f"[REPLICATE] Будет использован URL напрямую: {result_url[:100]}...")
                except Exception as e:
                    logger.error(f"[REPLICATE] Не удалось загрузить изображение по URL: {e}", exc_info=True)
            
            if result_data:
                logger.info(f"[REPLICATE] Возвращаем результат с данными изображения (размер: {len(result_data)} байт) и URL: {result_url[:100] if result_url else 'URL отсутствует'}...")
                return {
                    'success': True,
                    'image_url': result_url,
                    'image_data': result_data,
                    'error': None
                }
            elif result_url:
                logger.info(f"[REPLICATE] Возвращаем результат только с URL (данные изображения невалидны или отсутствуют): {result_url[:100]}...")
                return {
                    'success': True,
                    'image_url': result_url,
                    'image_data': None,
                    'error': None
                }
            else:
                logger.error(f"[REPLICATE] Не удалось получить результат генерации: нет ни данных, ни URL")
                raise ValueError("Не удалось получить результат генерации")
                
        except Exception as e:
            logger.error(f"[REPLICATE] Ошибка генерации: {e}", exc_info=True)
            
            # Улучшенное извлечение деталей ошибки
            error_message = str(e)
            
            # Если это ошибка от Replicate API, пытаемся извлечь больше деталей
            if hasattr(e, 'message'):
                error_message = str(e.message)
            elif hasattr(e, 'args') and len(e.args) > 0:
                error_message = str(e.args[0])
            
            # Проверяем наличие дополнительной информации в исключении
            error_details = []
            if hasattr(e, '__cause__') and e.__cause__:
                error_details.append(f"Причина: {str(e.__cause__)}")
            if hasattr(e, '__context__') and e.__context__:
                error_details.append(f"Контекст: {str(e.__context__)}")
            
            # Если есть детали, добавляем их к сообщению
            if error_details:
                error_message = f"{error_message} ({', '.join(error_details)})"
            
            logger.error(f"[REPLICATE] Детали ошибки: {error_message}")
            
            return {
                'success': False,
                'image_url': None,
                'image_data': None,
                'error': error_message
            }

