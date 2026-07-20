FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir \
    fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" aiosqlite asyncpg \
    pydantic pydantic-settings "python-jose[cryptography]" "passlib[bcrypt]" \
    redis httpx python-multipart

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
