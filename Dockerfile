# Stage 1: fetch and prepare frontend JS libraries (MathLive for Desmos-style
# math input, math.js for evaluation). Only needed at build time.
FROM node:20-alpine AS assets
WORKDIR /assets
RUN npm init -y >/dev/null 2>&1 && npm install mathlive mathjs
COPY build/generate-importmap.js ./generate-importmap.js
RUN node generate-importmap.js
RUN mkdir -p /out/mathlive && \
    (test -d node_modules/mathlive/dist && cp -r node_modules/mathlive/dist/. /out/mathlive/ || \
     cp -r node_modules/mathlive/*.mjs node_modules/mathlive/*.js node_modules/mathlive/fonts /out/mathlive/) && \
    (cp node_modules/mathjs/lib/browser/math.js /out/mathjs.min.js || \
     cp node_modules/mathjs/dist/math.min.js /out/mathjs.min.js || \
     cp node_modules/mathjs/dist/math.js /out/mathjs.min.js) && \
    cp out/import-map.json /out/import-map.json

# Stage 2: the actual app
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY --from=assets /out ./frontend/lib

# index.html hardcodes a default mathlive entry path for local/dev use;
# patch it to whatever generate-importmap.js actually resolved, in case a
# future mathlive release ships under a different filename.
RUN MATHLIVE_PATH=$(grep -oE '"mathlive": *"[^"]*"' frontend/lib/import-map.json | grep -oE '/lib/[^"]*') && \
    sed -i "s#/lib/mathlive/mathlive.min.mjs#${MATHLIVE_PATH}#" frontend/index.html

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/session', timeout=3)" || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
