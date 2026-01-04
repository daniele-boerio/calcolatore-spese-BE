from fastapi import FastAPI, Depends, HTTPException, status
from database import engine, get_db
import models, schemas, auth
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from services import task_aggiornamento_prezzi

# Inizializza lo scheduler globale
scheduler = BackgroundScheduler()

models.Base.metadata.create_all(bind=engine)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app = FastAPI(
    title="Calcolatore Spese API",
    description="Backend per la gestione finanze ed investimenti",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In produzione metteremo l'URL del frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Esegui ogni giorno alle 02:00 di notte
scheduler.add_job(task_aggiornamento_prezzi, 'cron', hour=2, minute=0)

@app.on_event("startup")
def start_scheduler():
    scheduler.start()

@app.get("/")
def read_root():
    return {"message": "Il backend del Calcolatore Spese è attivo!"}

@app.post("/register", response_model=schemas.UserOut)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # 1. Controlla se l'utente esiste già
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email già registrata")
    
    # 2. Hash della password
    hashed_pwd = auth.get_password_hash(user.password)
    
    # 3. Crea l'utente
    new_user = models.User(email=user.email, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Swagger invia l'email nel campo 'username' del form
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Credenziali non valide"
        )
    
    access_token = auth.create_access_token(data={"user_id": user.id})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/conti", response_model=schemas.ContoOut)
def create_conto(
    conto: schemas.ContoCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    new_conto = models.Conto(**conto.dict(), user_id=current_user_id)
    db.add(new_conto)
    db.commit()
    db.refresh(new_conto)
    return new_conto

@app.get("/conti", response_model=list[schemas.ContoOut])
def get_conti(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    return db.query(models.Conto).filter(models.Conto.user_id == current_user_id).all()

@app.post("/categorie", response_model=schemas.CategoriaOut)
def create_categoria(
    categoria: schemas.CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    new_cat = models.Categoria(**categoria.dict(), user_id=current_user_id)
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    return new_cat

@app.get("/categorie", response_model=list[schemas.CategoriaOut])
def get_categorie(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    return db.query(models.Categoria).filter(models.Categoria.user_id == current_user_id).all()

@app.post("/transazioni", response_model=schemas.TransazioneOut)
def create_transazione(
    transazione: schemas.TransazioneCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Controllo di sicurezza: il conto appartiene all'utente?
    conto = db.query(models.Conto).filter(
        models.Conto.id == transazione.conto_id, 
        models.Conto.user_id == current_user_id
    ).first()
    
    if not conto:
        raise HTTPException(status_code=404, detail="Conto non trovato o non autorizzato")

    # Se tutto ok, salviamo
    new_transazione = models.Transazione(**transazione.dict())
    db.add(new_transazione)
    db.commit()
    db.refresh(new_transazione)
    return new_transazione

@app.get("/transazioni", response_model=list[schemas.TransazioneOut])
def get_transazioni(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recuperiamo tutte le transazioni filtrando attraverso i conti dell'utente
    return db.query(models.Transazione).join(models.Conto).filter(
        models.Conto.user_id == current_user_id
    ).all()

# --- ENDPOINT INVESTIMENTI ---

@app.post("/investimenti", response_model=schemas.InvestimentoOut)
def create_investimento(
    investimento: schemas.InvestimentoCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Creiamo il titolo nell'anagrafica dell'utente
    new_invest = models.Investimento(**investimento.dict(), user_id=current_user_id)
    db.add(new_invest)
    db.commit()
    db.refresh(new_invest)
    return new_invest

@app.get("/investimenti", response_model=list[schemas.InvestimentoOut])
def get_investimenti(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Recupera tutti i titoli posseduti dall'utente
    return db.query(models.Investimento).filter(models.Investimento.user_id == current_user_id).all()

@app.post("/investimenti/operazione", response_model=schemas.StoricoInvestimentoOut)
def add_operazione_investimento(
    operazione: schemas.StoricoInvestimentoCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Controllo sicurezza: l'investimento appartiene all'utente loggato?
    investimento = db.query(models.Investimento).filter(
        models.Investimento.id == operazione.investimento_id,
        models.Investimento.user_id == current_user_id
    ).first()
    
    if not investimento:
        raise HTTPException(status_code=404, detail="Investimento non trovato o non autorizzato")

    new_record = models.StoricoInvestimento(**operazione.dict())
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record