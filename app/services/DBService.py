"""
Сервис для работы с базой данных
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from contextlib import contextmanager
from urllib.parse import quote_plus
import logging
from typing import Generator
from app.config import settings

logger = logging.getLogger(__name__)

class DBService:
    def __init__(self):
        self.Base = declarative_base()
        self.engine = None
        self.SessionLocal = None
        self._init_db()

    def _get_safe_db_url(self) -> str:
        """Генерирует безопасный URL подключения с экранированными спецсимволами"""
        try:
            safe_user = quote_plus(settings.POSTGRES_USER)
            safe_password = quote_plus(settings.POSTGRES_PASSWORD)
            safe_host = quote_plus(settings.POSTGRES_HOST)
            safe_db = quote_plus(settings.POSTGRES_DB)
            
            return (
                f"postgresql+psycopg2://{safe_user}:{safe_password}@"
                f"{safe_host}:{settings.POSTGRES_PORT}/{safe_db}"
                "?client_encoding=utf-8"
            )
        except Exception as e:
            logger.error(f"DB URL encoding error: {e}")
            raise

    def _init_db(self):
        """Инициализация подключения к БД"""
        try:
            db_url = self._get_safe_db_url()
            logger.info(f"Connecting to database...")
            
            self.engine = create_engine(
                db_url,
                pool_size=10,
                max_overflow=5,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={
                    "connect_timeout": 10,
                    "options": "-c statement_timeout=30000"
                },
                echo=False  # Отключено для продакшена
            )
            
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            logger.info("Database connection established successfully")
        except Exception as e:
            logger.critical(f"Database connection failed: {str(e)}")
            raise

    @contextmanager
    def get_session(self) -> Generator:
        """Контекстный менеджер для сессий"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database operation failed: {str(e)}")
            raise
        finally:
            session.close()

    def create_tables(self):
        """Создание таблиц в БД"""
        try:
            self.Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
            
            # Миграция: добавляем колонку model_name если её нет
            self._migrate_add_model_name_column()
        except Exception as e:
            logger.error(f"Failed to create tables: {str(e)}")
            raise
    
    def _migrate_add_model_name_column(self):
        """Добавляет колонку model_name в таблицу generations если её нет"""
        try:
            from sqlalchemy import text, inspect
            
            inspector = inspect(self.engine)
            
            # Проверяем, существует ли таблица
            if 'generations' not in inspector.get_table_names():
                logger.debug("[MIGRATION] Таблица generations не существует, пропускаем миграцию")
                return
            
            columns = [col['name'] for col in inspector.get_columns('generations')]
            
            if 'model_name' not in columns:
                logger.info("[MIGRATION] Добавление колонки model_name в таблицу generations...")
                with self.engine.begin() as conn:  # begin() автоматически делает commit
                    # Добавляем колонку
                    conn.execute(text("ALTER TABLE generations ADD COLUMN model_name VARCHAR"))
                    
                    # Проставляем значение по умолчанию для существующих записей
                    conn.execute(text("UPDATE generations SET model_name = 'nano-banana-pro' WHERE model_name IS NULL"))
                    
                logger.info("[MIGRATION] Колонка model_name успешно добавлена")
            else:
                logger.debug("[MIGRATION] Колонка model_name уже существует")
        except Exception as e:
            logger.warning(f"[MIGRATION] Ошибка при добавлении колонки model_name (не критично): {e}")
            # Не пробрасываем ошибку, чтобы не блокировать запуск приложения

# Инициализация сервиса
db_service = DBService()


