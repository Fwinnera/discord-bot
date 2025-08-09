# ---- Base image ----
FROM python:3.11-slim

# System deps (FFmpeg for audio)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# Copy requirements first (better layer caching), then install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your bot
COPY . .

# Environment
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV FFMPEG_PATH=/usr/bin/ffmpeg

# If your main file isn't main.py, change it here (e.g. "python your_bot.py")
CMD ["python", "main.py"]
