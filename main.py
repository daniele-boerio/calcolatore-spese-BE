import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from services import (
    task_aggiornamento_prezzi,
    task_transazioni_ricorrenti,
    task_ricarica_automatica_conti,
    task_sync_bank_connectors,
)
from routers import (
    auth,
    conti,
    categorie,
    transazioni,
    investimenti,
    user,
    sottocategorie,
    tag,
    debiti,
    ricorrenze,
    statistics,
    charts,
    bank_connectors,
    bank_proposals,
    open_banking,
)

logger = logging.getLogger(__name__)

# Lo scheduler gira IN-PROCESS: se l'app viene avviata con più worker
# (uvicorn/gunicorn --workers N) o scalata su più repliche, ogni processo ne
# avvia una copia e i job cron partono N volte (transazioni ricorrenti,
# ricariche e aggiornamenti prezzi duplicati). Deve quindi essere eseguito da
# un solo processo: il gate qui sotto lo tiene attivo di default (deploy a
# singolo worker) e va messo a "false" su tutte le repliche tranne una.
RUN_SCHEDULER = os.getenv("RUN_SCHEDULER", "true").lower() in ("1", "true", "yes")

scheduler = BackgroundScheduler()
scheduler.add_job(task_aggiornamento_prezzi, "cron", hour=2, minute=0)
scheduler.add_job(task_transazioni_ricorrenti, "cron", hour=3, minute=0)
scheduler.add_job(task_ricarica_automatica_conti, "cron", hour=4, minute=0)
# Ogni 6 ore (4 volte/giorno): le API AIS (PSD2) limitano gli accessi non
# presidiati, quindi una sync oraria genera 429 "Too Many Requests".
scheduler.add_job(task_sync_bank_connectors, "cron", hour="*/6")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if RUN_SCHEDULER:
        scheduler.start()
        logger.info("Scheduler avviato su questo processo")
    else:
        logger.info("Scheduler disabilitato su questo processo (RUN_SCHEDULER=false)")
    yield
    # Shutdown
    if RUN_SCHEDULER and scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Calcolatore Spese API",
    servers=[{"url": "/", "description": "Default"}],
    lifespan=lifespan,
)

# Middleware CORS (rimane qui)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://conti.spassocasa.it", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrazione dei Router
app.include_router(user.router)  # Gli endpoint di user (login/register)
app.include_router(conti.router)  # Gli endpoint dei conti
app.include_router(categorie.router)  # Categorie
app.include_router(sottocategorie.router)  # Sottocategorie
app.include_router(transazioni.router)  # Transazioni
app.include_router(investimenti.router)  # Investimenti
app.include_router(tag.router)  # Tag
app.include_router(ricorrenze.router)  # Ricorrenze
app.include_router(statistics.router)  # Statistiche
app.include_router(charts.router)  # API Grafici
app.include_router(bank_connectors.router)  # Connettore bancario
app.include_router(bank_proposals.router)  # Proposte di transazione (tutte le pending)
app.include_router(open_banking.router)  # Open Banking (GoCardless) requisition flow
app.include_router(debiti.router)  # Debiti
app.include_router(auth.router)  # Endpoint per forgot-password e reset-password


@app.get("/")
async def root():
    return {"status": "online", "message": "Backend SpassoConti attivo"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
