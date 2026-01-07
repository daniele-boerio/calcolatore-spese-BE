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
    allow_origins=["*"],       # Permette solo a queste origini di parlare col BE
    allow_credentials=True,
    allow_methods=["*"],         # Permette tutti i metodi (GET, POST, OPTIONS, ecc.)
    allow_headers=["*"],         # Permette tutti gli header (incluso Authorization)
)

# Esegui ogni giorno alle 02:00 di notte
scheduler.add_job(task_aggiornamento_prezzi, 'cron', hour=2, minute=0)

@app.on_event("startup")
def start_scheduler():
    scheduler.start()

@app.get("/")
def read_root():
    return {"message": "Il backend del Calcolatore Spese è attivo!"}

# --- ENDPOINT UTENTI ---

@app.post("/register", response_model=schemas.UserOut)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Controllo specifico per Email
    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="L'indirizzo email inserito è già associato a un account.")
    
    # Controllo specifico per Username
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Lo username scelto non è disponibile.")
    
    hashed_pwd = auth.get_password_hash(user.password)
    new_user = models.User(email=user.email, username=user.username, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    
    if not user:
        raise HTTPException(status_code=403, detail="Account non trovato. Verifica l'email inserita.")
    
    if not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Password errata. Riprova.")
    
    access_token = auth.create_access_token(data={"user_id": user.id})
    
    # Restituiamo il token insieme all'username recuperato dal DB
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "username": user.username # <--- Campo aggiunto
    }

# --- ENDPOINT CONTI ---

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

@app.put("/conti/{conto_id}", response_model=schemas.ContoOut)
def update_conto(conto_id: int, conto_data: schemas.ContoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_conto = db.query(models.Conto).filter(models.Conto.id == conto_id).first()

    if not db_conto:
        raise HTTPException(status_code=404, detail=f"Impossibile aggiornare: il conto con ID {conto_id} non esiste.")
    
    if db_conto.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Accesso negato: non hai i permessi per modificare questo conto.")

    for key, value in conto_data.dict().items():
        setattr(db_conto, key, value)

    db.commit()
    db.refresh(db_conto)
    return db_conto

@app.delete("/conti/{conto_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conto(
    conto_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_conto = db.query(models.Conto).filter(
        models.Conto.id == conto_id, 
        models.Conto.user_id == current_user_id
    ).first()

    if not db_conto:
        raise HTTPException(status_code=404, detail="Conto non trovato")

    # Nota: se elimini un conto, le transazioni collegate verranno eliminate 
    # se hai impostato il 'cascade delete' nei modelli.
    db.delete(db_conto)
    db.commit()
    return None

# --- ENDPOINT CATEGORIE ---

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

@app.put("/categorie/{categoria_id}", response_model=schemas.CategoriaOut)
def update_categoria(
    categoria_id: int, 
    cat_data: schemas.CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_cat = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()

    if not db_cat:
        raise HTTPException(status_code=404, detail=f"Categoria con ID {categoria_id} non trovata nel sistema.")
    
    if db_cat.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Non sei autorizzato a modificare questa categoria.")

    for key, value in cat_data.dict().items():
        setattr(db_cat, key, value)

    db.commit()
    db.refresh(db_cat)
    return db_cat

@app.delete("/categorie/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(
    categoria_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_cat = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()

    if not db_cat:
        raise HTTPException(status_code=404, detail="Impossibile eliminare: la categoria non esiste.")
    
    if db_cat.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Azione negata: non puoi eliminare categorie di altri utenti.")

    db.delete(db_cat)
    db.commit()
    return None

# --- ENDPOINT TRANSAZIONI ---

@app.post("/transazioni", response_model=schemas.TransazioneOut)
def create_transazione(
    transazione: schemas.TransazioneCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Verifichiamo che il conto scelto esista e appartenga all'utente loggato
    conto = db.query(models.Conto).filter(
        models.Conto.id == transazione.conto_id, 
        models.Conto.user_id == current_user_id
    ).first()
    
    if not conto:
        raise HTTPException(
            status_code=404, 
            detail=f"Il conto selezionato (ID: {transazione.conto_id}) non esiste o non ti appartiene."
        )

    # (Opzionale) Se è presente una categoria, verifichiamo che appartenga all'utente
    if transazione.categoria_id:
        cat = db.query(models.Categoria).filter(
            models.Categoria.id == transazione.categoria_id,
            models.Categoria.user_id == current_user_id
        ).first()
        if not cat:
            raise HTTPException(status_code=404, detail="La categoria selezionata non è valida per il tuo profilo.")

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

@app.put("/transazioni/{transazione_id}", response_model=schemas.TransazioneOut)
def update_transazione(
    transazione_id: int, 
    transazione_data: schemas.TransazioneCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Usiamo un JOIN per verificare la proprietà in una sola query
    db_transazione = db.query(models.Transazione).join(models.Conto).filter(
        models.Transazione.id == transazione_id, 
        models.Conto.user_id == current_user_id
    ).first()

    if not db_transazione:
        raise HTTPException(
            status_code=404, 
            detail="Transazione non trovata o non hai i permessi per modificarla."
        )

    for key, value in transazione_data.dict().items():
        setattr(db_transazione, key, value)

    db.commit()
    db.refresh(db_transazione)
    return db_transazione

@app.delete("/transazioni/{transazione_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transazione(
    transazione_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_transazione = db.query(models.Transazione).join(models.Conto).filter(
        models.Transazione.id == transazione_id, 
        models.Conto.user_id == current_user_id
    ).first()

    if not db_transazione:
        raise HTTPException(status_code=404, detail="Transazione non trovata")

    db.delete(db_transazione)
    db.commit()
    return None

# --- ENDPOINT INVESTIMENTI ---

@app.post("/investimenti", response_model=schemas.InvestimentoOut)
def create_investimento(investimento: schemas.InvestimentoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Evitiamo duplicati dello stesso ISIN per lo stesso utente
    existing = db.query(models.Investimento).filter(
        models.Investimento.isin == investimento.isin, 
        models.Investimento.user_id == current_user_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Il titolo con ISIN {investimento.isin} è già presente nel tuo portafoglio.")

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

@app.put("/investimenti/operazione/{operazione_id}", response_model=schemas.StoricoInvestimentoOut)
def update_operazione_investimento(
    operazione_id: int,
    operazione_data: schemas.StoricoInvestimentoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Verifichiamo che l'operazione esista e che l'investimento collegato appartenga all'utente
    db_operazione = db.query(models.StoricoInvestimento).join(models.Investimento).filter(
        models.StoricoInvestimento.id == operazione_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_operazione:
        raise HTTPException(status_code=404, detail="Operazione non trovata o non autorizzata")

    # Aggiorniamo i dati
    for key, value in operazione_data.dict().items():
        setattr(db_operazione, key, value)

    db.commit()
    db.refresh(db_operazione)
    return db_operazione

@app.delete("/investimenti/operazione/{operazione_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_operazione_investimento(
    operazione_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_operazione = db.query(models.StoricoInvestimento).join(models.Investimento).filter(
        models.StoricoInvestimento.id == operazione_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_operazione:
        raise HTTPException(status_code=404, detail="Operazione non trovata")

    db.delete(db_operazione)
    db.commit()
    return None

@app.put("/investimenti/{investimento_id}", response_model=schemas.InvestimentoOut)
def update_investimento(
    investimento_id: int,
    investimento_data: schemas.InvestimentoCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_investimento = db.query(models.Investimento).filter(
        models.Investimento.id == investimento_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_investimento:
        raise HTTPException(status_code=404, detail="Investimento non trovato")

    for key, value in investimento_data.dict().items():
        setattr(db_investimento, key, value)

    db.commit()
    db.refresh(db_investimento)
    return db_investimento

@app.delete("/investimenti/{investimento_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investimento(
    investimento_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_investimento = db.query(models.Investimento).filter(
        models.Investimento.id == investimento_id,
        models.Investimento.user_id == current_user_id
    ).first()

    if not db_investimento:
        raise HTTPException(status_code=404, detail="Investimento non trovato")

    # Grazie al cascade="all, delete-orphan" impostato nel modello, 
    # cancellando l'investimento verranno cancellate automaticamente 
    # anche tutte le sue operazioni nello storico.
    db.delete(db_investimento)
    db.commit()
    return None