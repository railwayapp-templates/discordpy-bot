FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r requirements.txt
COPY . .

# accounts.db lives here; mount a volume so it survives redeploys
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data

CMD ["python", "main.py"]
