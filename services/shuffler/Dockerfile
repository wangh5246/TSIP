FROM node:20-slim AS snarkjs
RUN npm config set registry https://registry.npmmirror.com \
    && (npm install -g snarkjs || npm install -g snarkjs --registry=https://registry.npmjs.org)

FROM python:3.10-slim
WORKDIR /app

COPY --from=snarkjs /usr/local/bin/node /usr/local/bin/node
COPY --from=snarkjs /usr/local/lib/node_modules/snarkjs /usr/local/lib/node_modules/snarkjs
RUN ln -sf /usr/local/lib/node_modules/snarkjs/build/cli.cjs /usr/local/bin/snarkjs \
    && chmod +x /usr/local/lib/node_modules/snarkjs/build/cli.cjs

COPY services/shuffler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/shuffler/app.py ./app.py
COPY common ./common
COPY zk ./zk

ENV PYTHONPATH=/app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
