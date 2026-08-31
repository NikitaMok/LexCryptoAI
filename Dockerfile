FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
      fastapi==0.115.6 \
      "uvicorn[standard]==0.34.0" \
      pydantic==2.10.4 \
      pydantic-settings==2.7.0 \
      python-multipart==0.0.20 \
      httpx==0.28.1 \
      python-dotenv==1.0.1 \
      PyYAML==6.0.2 \
      pdfplumber==0.11.4 \
      python-docx==1.2.0 \
      reportlab==5.0.1

COPY app ./app
COPY config ./config
COPY data/curated ./data/curated

ENV PYTHONPATH=/app
ENV APP_ENV=production
EXPOSE 8000

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
