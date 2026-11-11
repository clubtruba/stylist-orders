FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY app ./app
RUN pip install --no-cache-dir '.[dev]'
COPY migrations ./migrations
COPY tests ./tests
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
