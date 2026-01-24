# 🍌 Nano Banana Pro API - FastAPI версия

Адаптация проекта "ai SITE" для работы с Nano Banana Pro через Replicate API.

## ✨ Преимущества перед Streamlit версией

1. **Глобальная очередь** - все пользователи используют одну очередь генераций
2. **Масштабируемость** - легко добавить больше воркеров через `MAX_WORKERS`
3. **REST API** - можно использовать с любым фронтендом (React, Vue, Angular)
4. **Асинхронность** - генерации обрабатываются в фоне, не блокируя запросы
5. **Не требует GPU** - использует Replicate API (облачные вычисления)
6. **Пользовательские API ключи** - каждый пользователь может использовать свой ключ

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
cd api
pip install -r requirements.txt
```

### 2. Настройка окружения

Создайте файл `.env`:

```env
# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=nano_banana
POSTGRES_USER=nano_banana_user
POSTGRES_PASSWORD=nano_banana_pass

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=nano-banana-images
MINIO_USE_SSL=false
MINIO_PUBLIC_URL=http://localhost:9000

# Security
SECRET_KEY=your-secret-key-change-in-production-min-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=180
REFRESH_TOKEN_EXPIRE_DAYS=7
PWD_SCHEMES=bcrypt

# Replicate API (глобальный ключ)
REPLICATE_API_TOKEN=your_replicate_api_token_here

# Performance
MAX_WORKERS=3
MAX_CONCURRENT_GENERATIONS=3
```

### 3. Запуск через Docker (рекомендуется)

```bash
docker-compose up -d
```

### 4. Запуск без Docker

Сначала запустите PostgreSQL и MinIO, затем:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 📚 API Endpoints

### Аутентификация

- `POST /api/v1/auth/register` - Регистрация
- `POST /api/v1/auth/login` - Вход
- `GET /api/v1/auth/me` - Информация о текущем пользователе

### Генерация изображений

- `POST /api/v1/images/generate` - Создать задачу генерации
- `GET /api/v1/images/status/{generation_id}` - Статус генерации
- `GET /api/v1/images/list` - Список генераций пользователя
- `DELETE /api/v1/images/{generation_id}` - Удалить генерацию

### Управление API ключами

- `PUT /api/v1/users/api-key` - Установить API ключ Replicate
- `GET /api/v1/users/api-key` - Проверить наличие ключа
- `DELETE /api/v1/users/api-key` - Удалить ключ

## 🎯 Использование фронтенда

1. Откройте `frontend/index.html` в браузере
2. Зарегистрируйтесь или войдите
3. (Опционально) Установите свой API ключ Replicate
4. Заполните форму генерации и нажмите "Сгенерировать"

## 📝 Пример использования API

```python
import requests

API_URL = "http://localhost:8000/api/v1"

# Регистрация
response = requests.post(f"{API_URL}/auth/register", json={
    "username": "user1",
    "email": "user1@example.com",
    "password": "password123"
})
token = response.json()["access_token"]

# Установка API ключа
requests.put(
    f"{API_URL}/users/api-key",
    headers={"Authorization": f"Bearer {token}"},
    json={"api_key": "your_replicate_api_key"}
)

# Генерация изображения
response = requests.post(
    f"{API_URL}/images/generate",
    headers={"Authorization": f"Bearer {token}"},
    json={
        "prompt": "a beautiful landscape",
        "resolution": "1K",
        "aspect_ratio": "16:9",
        "generation_mode": "text-to-image"
    }
)
generation_id = response.json()["image_id"]

# Проверка статуса
response = requests.get(
    f"{API_URL}/images/status/{generation_id}",
    headers={"Authorization": f"Bearer {token}"}
)
print(response.json())
```

## 🔧 Архитектура

```
api/
├── app/
│   ├── main.py              # Точка входа FastAPI
│   ├── config.py           # Конфигурация
│   ├── models/
│   │   ├── base.py         # SQLAlchemy модели
│   │   ├── schemas.py      # Pydantic схемы
│   │   └── token.py        # Модели токенов
│   ├── routers/
│   │   ├── auth.py         # Аутентификация
│   │   ├── images.py       # Генерация изображений
│   │   └── users.py        # Управление пользователями
│   └── services/
│       ├── DBService.py    # Работа с БД
│       ├── ReplicateService.py  # Replicate API
│       ├── MinioService.py # MinIO хранилище
│       └── AuthService.py  # JWT аутентификация
├── frontend/
│   ├── index.html          # HTML интерфейс
│   ├── script.js           # JavaScript логика
│   └── styles.css          # Стили
├── requirements.txt        # Python зависимости
├── Dockerfile              # Docker образ
└── docker-compose.yml      # Docker Compose конфигурация
```

## 🔐 Безопасность

- ✅ JWT токены для аутентификации
- ✅ Хеширование паролей (bcrypt)
- ✅ CORS настройки
- ⚠️ **ВАЖНО**: В продакшене зашифруйте пользовательские API ключи перед сохранением в БД!

## 📊 Очередь генераций

- Максимум `MAX_WORKERS` (по умолчанию 3) генераций обрабатываются одновременно
- Новые задачи добавляются в очередь и обрабатываются по мере освобождения слотов
- Статусы: `pending` → `running` → `completed` / `failed`

## 🐛 Отладка

Логи выводятся в консоль. Для более детального логирования измените уровень в `main.py`:

```python
logging.basicConfig(level=logging.DEBUG)
```

## 📦 Деплой на Beget

1. Используйте SQLite вместо PostgreSQL (проще для Beget)
2. Используйте файловую систему вместо MinIO
3. Настройте Nginx как reverse proxy
4. Используйте systemd для автозапуска
5. Настройте SSL сертификат

Для деплоя: создайте `.env` из `env.example`, измените пароли и запустите `docker-compose up -d`

## 🔄 Миграция с Streamlit

Основные отличия:
- Streamlit: `st.session_state` (локальная очередь на пользователя)
- FastAPI: Глобальная очередь через ThreadPoolExecutor
- Streamlit: Встроенный UI
- FastAPI: REST API + отдельный фронтенд

## 📞 Поддержка

При возникновении проблем проверьте:
1. Логи приложения
2. Статус PostgreSQL и MinIO
3. Наличие API ключа Replicate
4. Правильность настроек в `.env`


