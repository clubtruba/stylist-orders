FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml backend/requirements.lock ./
COPY backend/app ./app
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
COPY bot/app ./bot_app
CMD ["python", "-m", "bot_app.main"]
