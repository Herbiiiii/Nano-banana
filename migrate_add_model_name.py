"""
Скрипт миграции: добавляет model_name="nano-banana-pro" для всех старых генераций,
где model_name = NULL
"""
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.DBService import db_service
from app.models.base import Generation
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_model_name():
    """Проставляет model_name="nano-banana-pro" для всех генераций, где model_name = NULL"""
    try:
        with db_service.get_session() as session:
            # Находим все генерации без model_name
            generations_without_model = session.query(Generation).filter(
                Generation.model_name.is_(None)
            ).all()
            
            count = len(generations_without_model)
            logger.info(f"[MIGRATION] Найдено генераций без model_name: {count}")
            
            if count == 0:
                logger.info("[MIGRATION] Миграция не требуется - все генерации уже имеют model_name")
                return
            
            # Обновляем все записи
            updated = 0
            for gen in generations_without_model:
                gen.model_name = "nano-banana-pro"
                # Также обновляем metadata для обратной совместимости
                if not gen.generation_metadata:
                    gen.generation_metadata = {}
                gen.generation_metadata['model_name'] = "nano-banana-pro"
                updated += 1
            
            session.commit()
            logger.info(f"[MIGRATION] Успешно обновлено генераций: {updated}")
            
    except Exception as e:
        logger.error(f"[MIGRATION] Ошибка миграции: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    logger.info("[MIGRATION] Начало миграции model_name...")
    migrate_model_name()
    logger.info("[MIGRATION] Миграция завершена")

