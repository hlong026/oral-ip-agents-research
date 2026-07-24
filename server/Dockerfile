FROM python:3.12-slim-bookworm

ARG DEBIAN_MIRROR=https://mirrors.aliyun.com
ARG PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH \
    PUBLISH_BROWSER_HEADLESS=true \
    PUBLISH_BROWSER_EXECUTABLE_PATH=/usr/bin/chromium

RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_MIRROR}/debian-security|g" \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}/debian|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends chromium ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /usr/sbin/nologin app

COPY server/pyproject.toml ./
COPY server/uv.lock ./
RUN pip install --no-cache-dir --index-url "${PYPI_INDEX_URL}" uv==0.11.6 \
    && uv export --locked --no-dev --no-emit-project --output-file /tmp/requirements.txt \
    && uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python --index-url "${PYPI_INDEX_URL}" --require-hashes --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY server/app ./app
COPY server/alembic.ini ./
COPY server/alembic ./alembic
COPY vendor/social-auto-upload /vendor/social-auto-upload
RUN mkdir -p /app/storage \
    && chown -R app:app /app /vendor /home/app \
    && chromium --version \
    && python -c "from app.providers.publish.sau_conf import setup_sau; setup_sau(); from uploader.douyin_uploader.main import cookie_auth; assert cookie_auth"

USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
