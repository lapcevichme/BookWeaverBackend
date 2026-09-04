FROM python:3.12-slim

# Настройка повторов apt при сбоях сетевого подключения к репозиториям debian
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80retries && \
    echo 'Acquire::http::Timeout "30";' >> /etc/apt/apt.conf.d/80retries && \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Кэширование и надежная установка зависимостей Python (с таймаутом 100с и ретраями)
COPY requirements.txt .
RUN pip install --default-timeout=100 --retries 5 --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения
COPY . .

# Создание необходимых папок для данных
RUN mkdir -p output input assets logs

EXPOSE 8000

CMD ["python", "api_server.py"]
