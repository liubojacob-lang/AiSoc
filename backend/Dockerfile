# AISOC backend image (multi-stage, non-root)
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -r aisoc && useradd -r -g aisoc aisoc
COPY --from=builder /install /usr/local
# run from source (cwd precedes site-packages on sys.path)
WORKDIR /srv/aisoc
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
# runtime-writable dirs: knowledge uploads land under BASE_DIR/data
RUN mkdir -p /srv/aisoc/data && chown -R aisoc:aisoc /srv/aisoc
USER aisoc
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/healthz')" || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
