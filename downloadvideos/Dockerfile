FROM python:3.12-slim

# Dependências do sistema (ffmpeg + timezone)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl tzdata && \
    rm -rf /var/lib/apt/lists/*

# Define fuso horário do contêiner
ENV TZ=America/Sao_Paulo

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ ./templates
COPY static/ ./static

RUN mkdir -p /app/downloads

EXPOSE 8085
# 1 worker, várias threads (SSE ok)
CMD ["gunicorn", "-b", "0.0.0.0:8085", "-w", "1", "--threads", "8", "--timeout", "120", "app:app"]
