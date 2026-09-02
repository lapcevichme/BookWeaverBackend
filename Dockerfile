FROM python:3.12-slim

# Установка системных утилит (ffmpeg для аудио и build-essential для C++ pywhispercpp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Кэширование и установка зависимостей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения
COPY . .

# Создание необходимых папок для данных
RUN mkdir -p output input assets logs

EXPOSE 8000

CMD ["python", "api_server.py"]
