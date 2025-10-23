FROM python:3.11-slim AS base
WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git fping --fix-missing && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt