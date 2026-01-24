"""
Сервис для работы с MinIO
"""
from minio import Minio
from minio.error import S3Error
from datetime import timedelta
from app.config import settings
import logging
import io
from typing import Dict

logger = logging.getLogger(__name__)

class MinioService:
    """Сервис для работы с MinIO хранилищем"""
    
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        self.bucket = settings.MINIO_BUCKET
        self.public_url = settings.MINIO_PUBLIC_URL
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Создает bucket если его нет"""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                # Делаем bucket публичным для чтения
                try:
                    from minio.commonconfig import REPLACE
                    from minio.deleteobjects import DeleteObject
                    self.client.set_bucket_policy(
                        self.bucket,
                        {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Principal": {"AWS": ["*"]},
                                    "Action": ["s3:GetObject"],
                                    "Resource": [f"arn:aws:s3:::{self.bucket}/*"]
                                }
                            ]
                        }
                    )
                except:
                    pass  # Если не получилось установить политику, продолжаем
                logger.info(f"[MINIO] Bucket {self.bucket} создан")
        except S3Error as e:
            logger.error(f"[MINIO] Ошибка создания bucket: {e}")
            raise

    def upload_image(self, image_data: bytes, filename: str, content_type: str = "image/jpeg") -> Dict[str, str]:
        """
        Загружает изображение в MinIO
        
        Returns:
            dict: {'url': str, 'path': str}
        """
        try:
            # Убеждаемся что filename начинается с images/
            if not filename.startswith('images/'):
                filename = f"images/{filename}"
            
            logger.info(f"[MINIO] Загрузка изображения: {filename}, размер: {len(image_data)} байт")
            
            self.client.put_object(
                self.bucket,
                filename,
                io.BytesIO(image_data),
                length=len(image_data),
                content_type=content_type
            )
            
            logger.info(f"[MINIO] Изображение успешно загружено: {filename}")
            
            # Используем публичный URL, так как bucket настроен как публичный
            # Это проще и надежнее, чем presigned URL, который требует правильной подписи
            base_url = self.public_url.rstrip('/')
            public_url = f"{base_url}/{self.bucket}/{filename}"
            logger.info(f"[MINIO] Сформирован публичный URL: {public_url}")
            
            return {
                'url': public_url,
                'path': filename
            }
        except S3Error as e:
            logger.error(f"[MINIO] Ошибка загрузки: {e}", exc_info=True)
            raise ValueError(f"MinIO upload error: {e}")
        except Exception as e:
            logger.error(f"[MINIO] Неожиданная ошибка при загрузке: {e}", exc_info=True)
            raise

    def get_image_url(self, filename: str, expires: int = 3600) -> str:
        """Получает presigned URL для изображения"""
        try:
            return self.client.presigned_get_object(
                self.bucket,
                filename,
                expires=timedelta(seconds=expires)
            )
        except S3Error:
            raise FileNotFoundError(f"Image {filename} not found")

    def delete_image(self, filename: str) -> bool:
        """Удаляет изображение из MinIO"""
        try:
            self.client.remove_object(self.bucket, filename)
            return True
        except S3Error as e:
            logger.error(f"[MINIO] Ошибка удаления: {e}")
            return False

