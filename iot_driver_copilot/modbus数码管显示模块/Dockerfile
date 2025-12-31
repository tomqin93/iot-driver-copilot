FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy driver code and dependency file first
COPY . /app

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose a default port (can be overridden by HTTP_PORT env at runtime)
EXPOSE 8000

# The driver reads all configuration from environment variables
ENTRYPOINT ["python", "-u", "driver.py"]
