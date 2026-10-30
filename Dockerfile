FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core ghostscript tesseract-ocr inkscape \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/assetsx
COPY pyproject.toml README.md ./
COPY assetsx_engine ./assetsx_engine
RUN pip install --no-cache-dir .
RUN useradd -m -u 10001 assetsx && mkdir -p /data/assetsx && chown -R assetsx:assetsx /data/assetsx
USER assetsx
ENV ASSETSX_ROOT=/data/assetsx PORT=8000
EXPOSE 8000
CMD ["assetsx-server"]
