FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
WORKDIR /service
COPY browser/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app/services/product_import.py ./app/services/product_import.py
COPY browser ./browser
USER pwuser
CMD ["xvfb-run", "-a", "python", "-m", "uvicorn", "browser.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
