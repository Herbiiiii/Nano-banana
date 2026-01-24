"""
Модели базы данных для Nano Banana Pro
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON, Float
from sqlalchemy.orm import relationship
from app.services.DBService import db_service

Base = db_service.Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)  # Переименовано из is_superuser
    replicate_api_key = Column(String, nullable=True)  # API ключ пользователя (зашифрован)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Связь 1 ко многим (User → Generations)
    generations = relationship("Generation", back_populates="user", cascade="all, delete-orphan")

class Generation(Base):
    __tablename__ = "generations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    prompt = Column(Text, nullable=False)
    enhanced_prompt = Column(Text, nullable=True)
    negative_prompt = Column(Text, nullable=True)
    generation_mode = Column(String, nullable=False)  # "text-to-image" или "image-to-image"
    resolution = Column(String, default="1K")
    aspect_ratio = Column(String, default="1:1")
    guidance_scale = Column(Float, default=7.5)
    num_inference_steps = Column(Integer, default=50)
    seed = Column(Integer, nullable=True)
    output_format = Column(String, default="jpg")
    result_url = Column(String, nullable=True)
    result_path = Column(String, nullable=True)
    result_data = Column(JSON, nullable=True)  # Метаданные изображения
    generation_metadata = Column(JSON, nullable=True)  # Дополнительные метаданные (переименовано из metadata, т.к. metadata зарезервировано в SQLAlchemy)
    status = Column(String, default="pending")  # pending, running, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Связь многие к 1 (Generation → User)
    user = relationship("User", back_populates="generations")

