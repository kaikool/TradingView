# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Cài chromium + chromedriver + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    fonts-liberation fonts-noto-color-emoji fonts-dejavu-core \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

# (Tùy chọn) timezone Asia/Bangkok
RUN ln -fs /usr/share/zoneinfo/Asia/Bangkok /etc/localtime && dpkg-reconfigure -f noninteractive tzdata

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Cloud Run sẽ đặt biến PORT, mặc định 8080
ENV PORT=8080 \
    PYTHONPATH=/app \
    # chỉ để chắc chắn chromium path trong 1 số môi trường
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Healthcheck (optional)
# HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:8080/health || exit 1

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host=0.0.0.0", "--port=8080"]
