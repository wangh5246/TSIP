FROM python:3.10-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g snarkjs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY services/charger/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/charger/app.py ./app.py
COPY common ./common

ENV PYTHONPATH=/app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
