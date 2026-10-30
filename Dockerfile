FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend ./frontend
COPY vite.config.js ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LOW_MEMORY_MODE=true OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY data/corpus.json data/pdf_books.json data/source_manifest.json data/devanagari_glyph_map.json ./data/
COPY data/pdfs ./data/pdfs
COPY data/models ./data/models
COPY data/rag-prepared ./data/rag-prepared
RUN python -m backend.manage setup-rag && python -m backend.manage init-db
COPY scripts ./scripts
COPY --from=frontend /app/dist ./dist
RUN useradd --create-home grantha && mkdir -p /app/instance && chown -R grantha:grantha /app
USER grantha
EXPOSE 8000
CMD ["sh", "-c", "python -m backend.manage init-db && gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 660 'backend.app:create_app()'"]
