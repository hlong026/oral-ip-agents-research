FROM python:3.12.13-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app

# Chromium 供真实平台发布；字体供封面绘制与 libass 中文字幕渲染。
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium ffmpeg fonts-noto-cjk \
    && useradd --create-home --uid 10001 oral \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.11.6@sha256:b1e699368d24c57cda93c338a57a8c5a119009ba809305cc8e86986d4a006754 /uv /uvx /bin/

COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev

COPY server/app ./app
COPY server/alembic.ini ./
COPY server/alembic ./alembic
COPY vendor/social-auto-upload /vendor/social-auto-upload

RUN mkdir -p /app/storage /vendor/social-auto-upload/cookies /vendor/social-auto-upload/logs \
    && chown -R oral:oral /app/storage /vendor/social-auto-upload \
    && python -c "from app.providers.publish.sau_conf import BASE_DIR, LOCAL_CHROME_PATH; assert BASE_DIR.is_dir(); assert LOCAL_CHROME_PATH"

EXPOSE 8000
USER oral
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
