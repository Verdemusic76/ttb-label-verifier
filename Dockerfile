FROM python:3.12-slim

# tesseract-ocr is only needed for the local-OCR extractor; harmless otherwise.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV EXTRACTOR=vision
EXPOSE 8000
# Bind to the platform-assigned $PORT (Render, Cloud Run, etc.); fall back to
# 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
