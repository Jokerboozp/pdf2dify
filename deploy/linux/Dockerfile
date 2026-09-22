FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src \
    HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1
WORKDIR /app
# Existing PDF modules import OpenCV/PDFium; install their Linux runtime libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY src ./src
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "ops_rag.cli", "--config", "/app/config.yaml", "serve", "--host", "0.0.0.0", "--port", "8765"]
