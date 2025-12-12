# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV TZ="US/Pacific"
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
# ffmpeg: for video processing
# curl: for healthchecks or downloading
RUN apt-get update && \
    apt-get install -y ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

# Create a non-privileged user
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

WORKDIR /app

# Install dependencies first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY . .

# Create directory structure for persistence and set permissions
# logs, images, db: ensuring they exist and are writable
RUN mkdir -p logs images db && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the Flask port
EXPOSE 5001

# Run the application directly
CMD ["python", "web_app.py"]
