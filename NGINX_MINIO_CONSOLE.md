# Настройка Nginx для MinIO Console

## Проблема
MinIO Console не открывается через `https://storage.ooneclickk.ru` потому что Nginx не настроен для проксирования порта 9001.

## Решение

Нужно добавить конфигурацию Nginx для проксирования MinIO Console на поддомене `storage.ooneclickk.ru`.

### Шаг 1: Создайте или обновите конфигурацию Nginx

На сервере создайте/обновите файл `/etc/nginx/sites-available/storage.ooneclickk.ru`:

```nginx
server {
    listen 80;
    server_name storage.ooneclickk.ru;
    
    # Редирект на HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name storage.ooneclickk.ru;

    # SSL сертификаты (уже должны быть настроены)
    ssl_certificate /etc/letsencrypt/live/storage.ooneclickk.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/storage.ooneclickk.ru/privkey.pem;

    # Проксирование MinIO API (порт 9000)
    location / {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Для WebSocket (если нужно)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Таймауты
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }

    # Проксирование MinIO Console (порт 9001)
    location /console/ {
        proxy_pass http://localhost:9001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Для WebSocket
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Таймауты
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;
    }
}
```

### Шаг 2: Обновите .env файл

В вашем `.env` файле измените:

```env
MINIO_CONSOLE_URL=https://storage.ooneclickk.ru/console
```

### Шаг 3: Перезапустите Nginx

```bash
sudo nginx -t  # Проверка конфигурации
sudo systemctl reload nginx
```

### Шаг 4: Перезапустите Docker контейнеры

```bash
cd ~/Nano-banana
docker-compose down
docker-compose up -d
```

### Шаг 5: Проверьте доступ

Откройте в браузере: `https://storage.ooneclickk.ru/console`

**Логин:** NanoBananoCorps  
**Пароль:** HWRYrAz20QFL9df

## Альтернативный вариант (отдельный порт)

Если хотите использовать отдельный порт для консоли, можно настроить так:

```nginx
server {
    listen 443 ssl http2;
    server_name storage.ooneclickk.ru:9001;

    ssl_certificate /etc/letsencrypt/live/storage.ooneclickk.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/storage.ooneclickk.ru/privkey.pem;

    location / {
        proxy_pass http://localhost:9001;
        # ... остальные настройки как выше
    }
}
```

Но первый вариант (с `/console/`) более удобен.

