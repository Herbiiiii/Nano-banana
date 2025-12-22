# 🐳 Docker Setup - Nano Banana Pro с MinIO и PostgreSQL

Полная настройка приложения с хранением данных в MinIO (изображения) и PostgreSQL (текстовые данные).

## 🚀 Быстрый старт

### 1. Подготовка

```bash
# Скопируйте .env.example в .env
cp .env.example .env

# Отредактируйте .env и добавьте ваш REPLICATE_API_TOKEN
# REPLICATE_API_TOKEN=r8_ваш_ключ_здесь
```

### 2. Запуск

```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

### 3. Доступ к сервисам

- **Streamlit приложение**: http://localhost:8501
- **MinIO Console**: http://localhost:9001 (minioadmin / minioadmin123)
- **MinIO API**: http://localhost:9000
- **PostgreSQL**: localhost:5432

## 📦 Что включено

### Сервисы:

1. **PostgreSQL** - база данных для истории генераций
2. **MinIO** - объектное хранилище для изображений
3. **Streamlit App** - веб-интерфейс

## 🔧 Настройка

### Переменные окружения (.env)

```env
# Обязательно
REPLICATE_API_TOKEN=your_token_here

# PostgreSQL (по умолчанию)
POSTGRES_DB=nano_banana
POSTGRES_USER=nano_banana_user
POSTGRES_PASSWORD=nano_banana_pass

# MinIO (по умолчанию)
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=nano-banana-images
```

### Изменение паролей

Отредактируйте `docker-compose.yml` или создайте `.env` файл:

```yaml
environment:
  POSTGRES_PASSWORD: ваш_безопасный_пароль
  MINIO_ROOT_PASSWORD: ваш_безопасный_пароль
```

## 📊 Структура данных

### PostgreSQL

**Таблица `generations`:**
- `id` - уникальный ID
- `timestamp` - время генерации
- `prompt` - текстовый промпт
- `image_url` - URL оригинального изображения (Replicate)
- `image_path` - путь в MinIO
- `params` - параметры генерации (JSON)
- `user_session_id` - ID сессии пользователя

### MinIO

**Bucket: `nano-banana-images`**
- Структура: `images/YYYYMMDD_HHMMSS_UUID.png`
- Публичный доступ для чтения

## 🔍 Полезные команды

### Просмотр логов

```bash
# Все сервисы
docker-compose logs -f

# Конкретный сервис
docker-compose logs -f app
docker-compose logs -f postgres
docker-compose logs -f minio
```

### Подключение к БД

```bash
# Через docker exec
docker-compose exec postgres psql -U nano_banana_user -d nano_banana

# Или через внешний клиент
# Host: localhost
# Port: 5432
# User: nano_banana_user
# Password: nano_banana_pass
# Database: nano_banana
```

### Работа с MinIO

```bash
# Через MinIO Client
docker-compose exec minio-setup mc ls myminio/nano-banana-images/

# Или через веб-интерфейс
# http://localhost:9001
```

### Перезапуск сервисов

```bash
# Перезапуск всех
docker-compose restart

# Перезапуск конкретного
docker-compose restart app
```

### Очистка данных

```bash
# Остановка и удаление контейнеров
docker-compose down

# Удаление с данными (ОСТОРОЖНО!)
docker-compose down -v
```

## 🗄️ Резервное копирование

### PostgreSQL

```bash
# Создание бэкапа
docker-compose exec postgres pg_dump -U nano_banana_user nano_banana > backup.sql

# Восстановление
docker-compose exec -T postgres psql -U nano_banana_user nano_banana < backup.sql
```

### MinIO

```bash
# Копирование bucket
docker-compose exec minio-setup mc mirror myminio/nano-banana-images ./backup/
```

## 🐛 Решение проблем

### Приложение не запускается

```bash
# Проверьте логи
docker-compose logs app

# Проверьте, что все сервисы запущены
docker-compose ps
```

### Ошибка подключения к БД

```bash
# Проверьте, что PostgreSQL запущен
docker-compose ps postgres

# Проверьте логи
docker-compose logs postgres
```

### Ошибка MinIO

```bash
# Проверьте bucket
docker-compose exec minio-setup mc ls myminio/

# Пересоздайте bucket
docker-compose exec minio-setup mc mb myminio/nano-banana-images
```

### Порт занят

Измените порты в `docker-compose.yml`:

```yaml
ports:
  - "8502:8501"  # Вместо 8501
  - "9002:9000"  # Вместо 9000
```

## 📈 Масштабирование

### Увеличение ресурсов

Отредактируйте `docker-compose.yml`:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

### Использование внешней БД

Измените `POSTGRES_HOST` в `.env` на адрес вашей БД.

## 🔒 Безопасность

### Для продакшена:

1. **Измените пароли** в `.env`
2. **Используйте SSL** для MinIO
3. **Ограничьте доступ** к портам
4. **Настройте firewall**
5. **Используйте secrets** вместо переменных окружения

## 📝 Примечания

- Данные сохраняются в Docker volumes
- При `docker-compose down -v` все данные удаляются
- MinIO bucket создается автоматически при первом запуске
- PostgreSQL таблицы создаются автоматически

## 🔗 Полезные ссылки

- [Docker Compose документация](https://docs.docker.com/compose/)
- [MinIO документация](https://min.io/docs/)
- [PostgreSQL документация](https://www.postgresql.org/docs/)

