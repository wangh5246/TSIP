FROM python:3.10-slim
WORKDIR /app

COPY services/aggregator_r/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/aggregator_r/app.py ./app.py
COPY common ./common

ENV PYTHONPATH=/app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
