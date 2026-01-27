"""
Сервис для логирования ошибок в файлы
"""
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Получаем путь к папке logs относительно корня проекта
def get_logs_dir():
    """Возвращает путь к папке logs"""
    # Путь относительно app/services/ErrorLogger.py
    # Нужно подняться на 2 уровня вверх: app/services -> app -> корень проекта
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(current_dir))
    return os.path.join(project_root, "logs")

def get_errors_dir():
    """Возвращает путь к папке errors"""
    errors_dir = os.path.join(get_logs_dir(), "errors")
    os.makedirs(errors_dir, exist_ok=True)
    return errors_dir

def save_error_to_file(error_data: dict):
    """Сохраняет ошибку в файл с датой и временем"""
    try:
        errors_dir = get_errors_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = os.path.join(errors_dir, f"error_{timestamp}.json")
        
        error_data['timestamp'] = datetime.now().isoformat()
        
        with open(error_file, 'w', encoding='utf-8') as f:
            json.dump(error_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[ERROR_LOG] Ошибка сохранена в {error_file}")
    except Exception as e:
        logger.error(f"[ERROR_LOG] Не удалось сохранить ошибку: {e}")


