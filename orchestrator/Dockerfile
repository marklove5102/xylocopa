FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y \
    git curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directories for volumes
RUN mkdir -p /app/db /app/backups /app/logs

# Git config — used when auto-initializing repos
RUN git config --global user.name "jyao97" \
    && git config --global user.email "contributor@example.com" \
    && git config --global init.defaultBranch main \
    && git config --global --add safe.directory "*"

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
