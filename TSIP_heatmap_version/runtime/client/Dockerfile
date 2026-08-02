FROM node:20-slim AS node_tools
WORKDIR /opt/tsip-v4
COPY runtime/js/package.json ./
COPY runtime/js/package-lock.json ./
RUN npm ci --omit=dev \
    && npm install -g snarkjs@0.7.6

FROM python:3.10-slim
WORKDIR /app

COPY --from=node_tools /usr/local/bin/node /usr/local/bin/node
COPY --from=node_tools /usr/local/lib/node_modules/snarkjs /usr/local/lib/node_modules/snarkjs
COPY --from=node_tools /opt/tsip-v4/node_modules /opt/tsip-v4/node_modules
RUN ln -sf /usr/local/lib/node_modules/snarkjs/build/cli.cjs /usr/local/bin/snarkjs \
    && chmod +x /usr/local/lib/node_modules/snarkjs/build/cli.cjs

COPY runtime/client/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY runtime/client/client.py ./client.py
COPY runtime/common ./common
COPY runtime/js ./v4/js
COPY zk ./v4/zk

ENV NODE_PATH=/opt/tsip-v4/node_modules
ENV PYTHONPATH=/app
CMD ["sleep", "infinity"]
