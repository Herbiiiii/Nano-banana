"""
Утилиты для работы с PostgreSQL
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from config import POSTGRES_CONFIG
import logging
import json

logger = logging.getLogger(__name__)

def get_db_connection():
    """Создает подключение к БД"""
    try:
        # Используем настройки из config, которые уже учитывают переменные окружения
        conn = psycopg2.connect(**POSTGRES_CONFIG, connect_timeout=10)
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return None

def init_database():
    """Инициализация таблиц БД"""
    # Отладка: логируем настройки подключения
    logger.info(f"Попытка подключения к БД: {POSTGRES_CONFIG}")
    conn = get_db_connection()
    if not conn:
        logger.error(f"Не удалось подключиться к БД с настройками: {POSTGRES_CONFIG}")
        return False
    
    try:
        with conn.cursor() as cur:
            # Таблица для истории генераций
            cur.execute("""
                CREATE TABLE IF NOT EXISTS generations (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    prompt TEXT NOT NULL,
                    image_url TEXT,
                    image_path TEXT,
                    params JSONB,
                    user_session_id TEXT
                )
            """)
            
            # Индекс для быстрого поиска по сессии
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_session 
                ON generations(user_session_id)
            """)
            
            # Индекс по времени
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON generations(timestamp DESC)
            """)
            
            conn.commit()
            logger.info("База данных инициализирована")
            return True
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def save_generation(prompt, image_url=None, image_path=None, params=None, session_id=None, negative_prompt=None):
    """Сохраняет генерацию в БД"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        # Добавляем negative_prompt в params если он есть
        if params is None:
            params = {}
        if negative_prompt:
            params['negative_prompt'] = negative_prompt
        
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO generations (prompt, image_url, image_path, params, user_session_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (prompt, image_url, image_path, json.dumps(params) if params else None, session_id))
            
            generation_id = cur.fetchone()[0]
            conn.commit()
            return generation_id
    except Exception as e:
        logger.error(f"Ошибка сохранения генерации: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def get_generations(session_id=None, limit=10):
    """Получает историю генераций"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if session_id:
                cur.execute("""
                    SELECT * FROM generations 
                    WHERE user_session_id = %s 
                    ORDER BY timestamp DESC 
                    LIMIT %s
                """, (session_id, limit))
            else:
                cur.execute("""
                    SELECT * FROM generations 
                    ORDER BY timestamp DESC 
                    LIMIT %s
                """, (limit,))
            
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Ошибка получения генераций: {e}")
        return []
    finally:
        conn.close()

