FROM python:3.14-slim

WORKDIR /app

# Installazione dipendenze di sistema
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiamo e installiamo i requirements PRIMA del resto del codice
# Così se cambi il codice, Docker non deve reinstallare tutte le librerie ogni volta
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ora copiamo il resto del codice
COPY . .

# Comando per avviare uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"]