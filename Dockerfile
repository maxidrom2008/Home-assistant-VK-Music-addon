FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 VKMS_DATA_DIR=/data VKMS_HOST=0.0.0.0 VKMS_PORT=8099
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data
EXPOSE 8099
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
