"""
Конфигурация для подключения к БД и MinIO
"""
import os

# PostgreSQL настройки
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', 5432)),  # Внутри Docker сети используется 5432
    'database': os.getenv('POSTGRES_DB', 'nano_banana'),
    'user': os.getenv('POSTGRES_USER', 'nano_banana_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'nano_banana_pass'),
}

# MinIO настройки
MINIO_CONFIG = {
    'endpoint': os.getenv('MINIO_ENDPOINT', 'localhost:9000'),
    'access_key': os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
    'secret_key': os.getenv('MINIO_SECRET_KEY', 'minioadmin123'),
    'bucket': os.getenv('MINIO_BUCKET', 'nano-banana-images'),
    'use_ssl': os.getenv('MINIO_USE_SSL', 'false').lower() == 'true',
}

# URL для доступа к MinIO (для отображения изображений)
MINIO_PUBLIC_URL = os.getenv('MINIO_PUBLIC_URL', 'http://localhost:9002')

