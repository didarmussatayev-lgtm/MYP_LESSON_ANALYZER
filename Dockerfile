# Лёгкий образ: локального Whisper больше нет (транскрипция ушла в Gemini API),
# поэтому системные зависимости минимальны - ffmpeg/libsndfile нужны только
# для librosa/soundfile (sync.py, кросс-корреляция аудио).

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY src/ ./src/
COPY config/ ./config/
COPY templates/ ./templates/
COPY app/ ./app/

RUN mkdir -p /srv/app/uploads /srv/app/output /srv/app/work

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Railway передаёт порт через переменную $PORT - используем её, если задана,
# иначе локальный дефолт 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
