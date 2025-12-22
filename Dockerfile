FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование приложения
COPY app.py .
COPY config.py .

# Открытие порта
EXPOSE 8501

# Запуск Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]

