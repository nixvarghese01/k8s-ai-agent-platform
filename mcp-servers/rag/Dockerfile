# One image for both the search server (Deployment mcp-rag) and the indexer (CronJob rag-index).
FROM python:3.13-slim
# OCR for scanned PDFs and images (Week 8): Tesseract (English) and poppler to render PDF pages
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# LlamaIndex counts tokens with tiktoken, which downloads its encoding on first use; bake it in
# so the pods need no internet and can keep a read-only root filesystem
ENV TIKTOKEN_CACHE_DIR=/app/tiktoken
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY rag_store.py rag_index.py rag_server.py ./
USER 1000
ENV PYTHONUNBUFFERED=1 FILES_ROOT=/data
EXPOSE 8000
CMD ["python", "rag_server.py"]
