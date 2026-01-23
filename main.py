from fastapi import FastAPI
from database import engine
import models
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from services import task_aggiornamento_prezzi, task_transazioni_ricorrenti, task_ricarica_automatica_conti
from routers import conti, categorie, transazioni, investimenti, budget, user, sottocategorie, tag, ricorrenze

app = FastAPI(title="Calcolatore Spese API")

# Middleware CORS (rimane qui)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrazione dei Router
app.include_router(user.router)           # Gli endpoint di user (login/register)
app.include_router(conti.router)          # Gli endpoint dei conti
app.include_router(categorie.router)      # Categorie
app.include_router(sottocategorie.router) # Sottocategorie
app.include_router(transazioni.router)    # Transazioni
app.include_router(investimenti.router)   # Investimenti
app.include_router(tag.router)            # Tag
app.include_router(ricorrenze.router)     # Ricorrenze

# Scheduler (rimane qui)
scheduler = BackgroundScheduler()
scheduler.add_job(task_aggiornamento_prezzi, 'cron', hour=2, minute=0)
scheduler.add_job(task_transazioni_ricorrenti, 'cron', hour=3, minute=0)
scheduler.add_job(task_ricarica_automatica_conti, 'cron', hour=4, minute=0)

@app.on_event("startup")
def start_scheduler():
    scheduler.start()

@app.get("/")
def read_root():
    return {"message": "Backend attivo e modulare!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")