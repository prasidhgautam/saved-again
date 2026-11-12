FROM node:24-bookworm-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.* ./
COPY src ./src
COPY public ./public
COPY scripts/prepare-sites-build.mjs ./scripts/prepare-sites-build.mjs
COPY worker ./worker
COPY .openai ./.openai
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SAVEDAGAIN_DATA=/data
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd -m -u 10001 savedagain && mkdir /data && chown savedagain:savedagain /data
COPY --chown=savedagain:savedagain backend ./backend
COPY --from=frontend --chown=savedagain:savedagain /app/dist/client ./dist/client
USER savedagain
EXPOSE 8765
CMD ["python","-m","uvicorn","backend.server:app","--host","0.0.0.0","--port","8765"]
