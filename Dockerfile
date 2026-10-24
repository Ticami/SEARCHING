# SEARCHING no modo hospedado: frontend compilado + API Flask atrás do gunicorn. HTTPS fica a cargo do proxy (veja docker-compose.yml).
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 SEARCHING_MODO=hospedado SEARCHING_PRINTS=/dados/prints
WORKDIR /app/backend
COPY backend/requirements.txt backend/requirements-hospedado.txt ./
RUN pip install --no-cache-dir -r requirements-hospedado.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN useradd --system --uid 10001 searching && mkdir -p /dados/prints && chown -R searching /dados
USER searching
VOLUME ["/dados"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# /api/health é a única rota que aceita o Host interno (o resto é conferido contra SEARCHING_URL_PUBLICA).
# Cria/atualiza as tabelas uma vez antes de subir os workers (evita corrida entre eles no primeiro início).
CMD ["sh", "-c", "python -c 'from searching.db.session import criar_engine, iniciar_banco; iniciar_banco(criar_engine())' && exec gunicorn -b 0.0.0.0:8000 -w 2 --threads 4 server:app"]
