# syntax=docker/dockerfile:1
#
# Gesart - gestionale articoli (immagine di produzione)
#
# Build:  docker build -t gesart .
# Run:    docker run -p 9080:9080 -v gesart-data:/data gesart

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GESART_DATA_DIR=/data \
    GESART_IMPORTS_DIR=/imports \
    GESART_HOST=0.0.0.0 \
    GESART_PORT=9080

# curl serve al HEALTHCHECK; tzdata serve alle date localizzate dei listini.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/gesart

# Prima le dipendenze: la layer si riusa a ogni rebuild del codice.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Utente non privilegiato con home e directory dati di sua proprietà.
RUN useradd --system --create-home --uid 1000 --home-dir /home/gesart gesart \
    && mkdir -p /data /imports \
    && chown -R gesart:gesart /data /imports /srv/gesart

USER gesart

VOLUME ["/data", "/imports"]
EXPOSE 9080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${GESART_PORT}/healthz" || exit 1

CMD ["python", "-m", "uvicorn", "app.web.main:app", "--host", "0.0.0.0", "--port", "9080", "--proxy-headers"]
