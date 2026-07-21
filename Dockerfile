FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

RUN playwright install firefox && playwright install-deps firefox

COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

COPY . .

ENV PYTHONPATH=/app
ENV DISPLAY=:99

ENTRYPOINT ["./docker-entrypoint.sh"]
