FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Run as a non-root user.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

# ffmpeg lets PyDub decode WebM / MP4 / OGG / MP3 recordings.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Install dependencies first so Docker can cache this layer.
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ ./
# Private, non-public directory for TEMPORARY candidate audio (shared with the worker via a volume).
RUN mkdir -p /var/hireiq/audio_tmp && chmod 700 /var/hireiq/audio_tmp \
 && chown -R app:app /app /var/hireiq
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
