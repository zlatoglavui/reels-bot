FROM python:3.11-slim

WORKDIR /app

# FFmpeg + шрифты для субтитров
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    fonts-dejavu-core \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Скачиваем шрифт с поддержкой кириллицы
RUN wget -q -O /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf \
    https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans-Bold.ttf \
    || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
