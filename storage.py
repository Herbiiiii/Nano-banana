"""
Утилиты для работы с MinIO
"""
from minio import Minio
from minio.error import S3Error
from config import MINIO_CONFIG, MINIO_PUBLIC_URL
import io
import logging
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Инициализация MinIO клиента
try:
    minio_client = Minio(
        MINIO_CONFIG['endpoint'],
        access_key=MINIO_CONFIG['access_key'],
        secret_key=MINIO_CONFIG['secret_key'],
        secure=MINIO_CONFIG['use_ssl']
    )
except Exception as e:
    logger.error(f"Ошибка инициализации MinIO: {e}")
    minio_client = None

def ensure_bucket():
    """Создает bucket если его нет"""
    if not minio_client:
        return False
    
    try:
        if not minio_client.bucket_exists(MINIO_CONFIG['bucket']):
            minio_client.make_bucket(MINIO_CONFIG['bucket'])
            logger.info(f"Bucket {MINIO_CONFIG['bucket']} создан")
        return True
    except S3Error as e:
        logger.error(f"Ошибка создания bucket: {e}")
        return False

def upload_image(image_data, filename=None):
    """Загружает изображение в MinIO"""
    if not minio_client:
        return None
    
    ensure_bucket()
    
    try:
        if filename is None:
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
        
        # Убеждаемся, что filename начинается с правильного префикса
        if not filename.startswith('images/'):
            filename = f"images/{filename}"
        
        # Загружаем изображение
        image_bytes = io.BytesIO(image_data)
        image_bytes.seek(0)
        
        minio_client.put_object(
            MINIO_CONFIG['bucket'],
            filename,
            image_bytes,
            length=len(image_data),
            content_type='image/png'
        )
        
        # Возвращаем публичный URL
        public_url = f"{MINIO_PUBLIC_URL}/{MINIO_CONFIG['bucket']}/{filename}"
        return {
            'url': public_url,
            'path': filename
        }
    except S3Error as e:
        logger.error(f"Ошибка загрузки в MinIO: {e}")
        return None

def download_image(object_name):
    """Скачивает изображение из MinIO"""
    if not minio_client:
        return None
    
    try:
        response = minio_client.get_object(MINIO_CONFIG['bucket'], object_name)
        return response.read()
    except S3Error as e:
        logger.error(f"Ошибка скачивания из MinIO: {e}")
        return None

def delete_image(object_name):
    """Удаляет изображение из MinIO"""
    if not minio_client:
        return False
    
    try:
        minio_client.remove_object(MINIO_CONFIG['bucket'], object_name)
        return True
    except S3Error as e:
        logger.error(f"Ошибка удаления из MinIO: {e}")
        return False

