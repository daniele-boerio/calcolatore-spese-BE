# Usa un'immagine Python leggera e recente
FROM python:3.14-slim

# Imposta variabili d'ambiente per evitare file .pyc e forzare l'output log
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Imposta la cartella di lavoro
WORKDIR /app

# Installa le dipendenze di sistema necessarie per psycopg2 e l'health check
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia solo il file dei requirements per sfruttare la cache di Docker
COPY requirements.txt .

# Installa le dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia tutto il resto del codice del progetto
COPY . .

# Espone la porta su cui girerà l'app
EXPOSE 8000

# Comando di avvio:
# 1. Esegue le migrazioni di Alembic per aggiornare il database
# 2. Avvia Uvicorn configurato per gestire proxy e documentazione corretta
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=* --root-path /"]
