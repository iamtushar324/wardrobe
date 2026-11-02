# syntax=docker/dockerfile:1
# One image for both processes: the web app (default) and the background worker
#   docker run ... wardrobe                       -> web + API + MCP on :8080
#   docker run ... wardrobe python -m wardrobe.worker
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN useradd --uid 65532 --user-group --no-create-home --shell /usr/sbin/nologin wardrobe
WORKDIR /app
COPY server/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY server/wardrobe /app/wardrobe
COPY --from=web /web/dist /app/web
RUN chmod -R a+rX /app
ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_VERSION=${APP_VERSION} \
    WARDROBE_DATA_DIR=/data WARDROBE_WEB_DIR=/app/web
USER 65532:65532
EXPOSE 8080
CMD ["uvicorn", "wardrobe.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
