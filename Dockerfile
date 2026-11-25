# Build the frontend
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Run the API + static site. Embeddings use the built-in TF-IDF fallback to stay within free-tier memory.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY forgeai/ forgeai/
RUN pip install --no-cache-dir -e ".[ui,xlsx]"
COPY demos/ demos/
COPY runs/ runs/
COPY --from=web /web/dist web/dist
ENV FORGE_PUBLIC=1 FORGE_EMBED_BACKEND=tfidf PYTHONUNBUFFERED=1 PORT=7860
RUN useradd --create-home forge && chown -R forge /app
USER forge
EXPOSE 7860
CMD ["sh", "-c", "uvicorn forgeai.server:app --host 0.0.0.0 --port ${PORT}"]
