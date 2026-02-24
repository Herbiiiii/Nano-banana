# Инструкция по миграции: добавление колонки model_name

## Проблема
Колонка `model_name` отсутствует в таблице `generations` в базе данных.

## Решение

### Автоматическая миграция (рекомендуется)
При следующем запуске приложения миграция выполнится автоматически через `DBService._migrate_add_model_name_column()`.

### Ручная миграция через Docker

Если автоматическая миграция не сработала, выполните SQL вручную:

#### Вариант 1: Через docker exec
```bash
# Подключиться к контейнеру PostgreSQL
docker exec -it nano_banana_postgres psql -U nano_banana_user -d nano_banana

# Затем выполнить SQL:
ALTER TABLE generations ADD COLUMN model_name VARCHAR;
UPDATE generations SET model_name = 'nano-banana-pro' WHERE model_name IS NULL;
```

#### Вариант 2: Через SQL файл
```bash
# Скопировать SQL файл в контейнер и выполнить
docker cp migrate_add_model_name_column.sql nano_banana_postgres:/tmp/
docker exec -it nano_banana_postgres psql -U nano_banana_user -d nano_banana -f /tmp/migrate_add_model_name_column.sql
```

#### Вариант 3: Через docker-compose exec
```bash
docker-compose exec postgres psql -U nano_banana_user -d nano_banana -c "ALTER TABLE generations ADD COLUMN model_name VARCHAR;"
docker-compose exec postgres psql -U nano_banana_user -d nano_banana -c "UPDATE generations SET model_name = 'nano-banana-pro' WHERE model_name IS NULL;"
```

## Проверка
После миграции проверьте, что колонка добавлена:
```bash
docker exec -it nano_banana_postgres psql -U nano_banana_user -d nano_banana -c "\d generations"
```

Должна появиться колонка `model_name`.

