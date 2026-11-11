FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir '.[bot]'
COPY bot/app ./bot_app
CMD ["python", "-m", "bot_app.main"]
