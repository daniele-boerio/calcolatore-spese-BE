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

@app.post("/register", response_model=schemas.Token)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # 1. Controllo duplicati
    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="L'indirizzo email inserito è già associato a un account.")
    
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Lo username scelto non è disponibile.")
    
    # 2. Hash della password e creazione utente
    hashed_pwd = auth.get_password_hash(user.password)
    new_user = models.User(
        email=user.email, 
        username=user.username, 
        hashed_password=hashed_pwd
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 3. Generazione Token per login automatico
    access_token = auth.create_access_token(data={"user_id": new_user.id})
    
    return {
        "access_token": access_token,
        "username": new_user.username
    }

@app.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Cerchiamo l'utente direttamente tramite lo username
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Account non trovato. Verifica lo username inserito."
        )
    
    if not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Password errata. Riprova."
        )
    
    access_token = auth.create_access_token(data={"user_id": user.id})
    
    return {
        "access_token": access_token,
        "username": user.username
    }

# --- ENDPOINT CONTI ---

@app.post("/conto", response_model=schemas.ContoOut)
def create_conto(
    conto: schemas.ContoCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    new_conto = models.Conto(**conto.model_dump(), user_id=current_user_id)
    db.add(new_conto)
    db.commit()
    db.refresh(new_conto)
    return new_conto

@app.get("/conti", response_model=list[schemas.ContoOut])
def get_conti(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    return db.query(models.Conto).filter(models.Conto.user_id == current_user_id).order_by(models.Conto.id).all()

@app.put("/conto/{conto_id}", response_model=schemas.ContoOut)
def update_conto(conto_id: int, conto_data: schemas.ContoUpdate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    db_conto = db.query(models.Conto).filter(models.Conto.id == conto_id).first()

    if not db_conto:
        raise HTTPException(status_code=404, detail=f"Impossibile aggiornare: il conto con ID {conto_id} non esiste.")
    
    if db_conto.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Accesso negato: non hai i permessi per modificare questo conto.")

    for key, value in conto_data.model_dump().items():
        setattr(db_conto, key, value)

    db.commit()
    db.refresh(db_conto)
    return db_conto

@app.delete("/conto/{conto_id}", status_code=status.HTTP_204_NO_CONTENT)
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

@app.post("/categoria", response_model=schemas.CategoriaOut)
def create_categoria(
    categoria: schemas.CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Estraiamo i dati escludendo le sottocategorie per creare la categoria madre
    categoria_data = categoria.model_dump(exclude={'sottocategorie'})
    new_cat = models.Categoria(**categoria_data, user_id=current_user_id)
    
    # 2. Se sono presenti sottocategorie, le trasformiamo in modelli SQLAlchemy
    if categoria.sottocategorie:
        for sub_data in categoria.sottocategorie:
            # Creiamo l'oggetto sottocategoria collegandolo alla categoria madre
            new_sub = models.Sottocategoria(nome=sub_data.nome)
            new_cat.sottocategorie.append(new_sub)

    db.add(new_cat)
    
    try:
        db.commit()
        db.refresh(new_cat)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Errore durante la creazione della categoria e sottocategorie")
        
    return new_cat

@app.get("/categorie", response_model=list[schemas.CategoriaOut])
def get_categorie(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recupera le categorie e le loro sottocategorie associate
    return db.query(models.Categoria).filter(
        models.Categoria.user_id == current_user_id
    ).order_by(models.Categoria.nome).all()

@app.put("/categoria/{categoria_id}", response_model=schemas.CategoriaOut)
def update_categoria(
    categoria_id: int, 
    cat_data: schemas.CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Cerchiamo la categoria verificando che appartenga all'utente
    db_cat = db.query(models.Categoria).filter(
        models.Categoria.id == categoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_cat:
        raise HTTPException(
            status_code=404, 
            detail="Categoria non trovata o non disponi dei permessi necessari."
        )

    # Aggiorniamo solo il nome della categoria principale
    db_cat.nome = cat_data.nome

    db.commit()
    db.refresh(db_cat)
    return db_cat

@app.delete("/categoria/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(
    categoria_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_cat = db.query(models.Categoria).filter(
        models.Categoria.id == categoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_cat:
        raise HTTPException(status_code=404, detail="Categoria non esistente.")

    db.delete(db_cat)
    db.commit()
    return None

# --- ENDPOINT SOTTOCATEGORIE (OPERAZIONI SINGOLE) ---

@app.post("/categorie/{categoria_id}/sottocategorie", response_model=list[schemas.SottocategoriaOut])
def add_sottocategorie(
    categoria_id: int,
    sub_data_list: list[schemas.SottocategoriaCreate], # Accetta una lista
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Verifica proprietà della categoria padre
    db_cat = db.query(models.Categoria).filter(
        models.Categoria.id == categoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_cat:
        raise HTTPException(status_code=404, detail="Categoria padre non trovata o non autorizzata")

    # 2. Crea e aggiungi ogni sottocategoria della lista
    new_subcategories = []
    for sub_data in sub_data_list:
        new_sub = models.Sottocategoria(
            nome=sub_data.nome, 
            categoria_id=categoria_id
        )
        db.add(new_sub)
        new_subcategories.append(new_sub)

    # 3. Commit unico per tutte le nuove sottocategorie
    db.commit()
    
    # Rinfresca gli oggetti per ottenere gli ID generati
    for sub in new_subcategories:
        db.refresh(sub)
        
    return new_subcategories

@app.put("/sottocategoria/{sottocategoria_id}", response_model=schemas.SottocategoriaOut)
def update_sottocategoria(
    sottocategoria_id: int,
    sub_data: schemas.SottocategoriaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # JOIN per verificare che il proprietario della categoria sia l'utente corrente
    db_sub = db.query(models.Sottocategoria).join(models.Categoria).filter(
        models.Sottocategoria.id == sottocategoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_sub:
        raise HTTPException(status_code=404, detail="Sottocategoria non trovata o non autorizzato")

    db_sub.nome = sub_data.nome
    db.commit()
    db.refresh(db_sub)
    return db_sub

@app.delete("/sottocategoria/{sottocategoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sottocategoria(
    sottocategoria_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Verifichiamo proprietà tramite join
    db_sub = db.query(models.Sottocategoria).join(models.Categoria).filter(
        models.Sottocategoria.id == sottocategoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_sub:
        raise HTTPException(status_code=404, detail="Sottocategoria non trovata")

    # Gestione integrità transazioni: setta a NULL le transazioni collegate
    db.query(models.Transazione).filter(
        models.Transazione.sottocategoria_id == sottocategoria_id
    ).update({models.Transazione.sottocategoria_id: None})

    db.delete(db_sub)
    db.commit()
    return None

# --- ENDPOINT TRANSAZIONI ---

@app.post("/transazione", response_model=schemas.TransazioneOut)
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

    new_transazione = models.Transazione(**transazione.model_dump())
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

@app.put("/transazione/{transazione_id}", response_model=schemas.TransazioneOut)
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

    for key, value in transazione_data.model_dump().items():
        setattr(db_transazione, key, value)

    db.commit()
    db.refresh(db_transazione)
    return db_transazione

@app.delete("/transazione/{transazione_id}", status_code=status.HTTP_204_NO_CONTENT)
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

@app.post("/investimento", response_model=schemas.InvestimentoOut)
def create_investimento(investimento: schemas.InvestimentoCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Evitiamo duplicati dello stesso ISIN per lo stesso utente
    existing = db.query(models.Investimento).filter(
        models.Investimento.isin == investimento.isin, 
        models.Investimento.user_id == current_user_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Il titolo con ISIN {investimento.isin} è già presente nel tuo portafoglio.")

    new_invest = models.Investimento(**investimento.model_dump(), user_id=current_user_id)
    db.add(new_invest)
    db.commit()
    db.refresh(new_invest)
    return new_invest

@app.get("/investimenti", response_model=list[schemas.InvestimentoOut])
def get_investimenti(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    # Recupera tutti i titoli posseduti dall'utente
    return db.query(models.Investimento).filter(models.Investimento.user_id == current_user_id).all()

@app.post("/investimento/operazione", response_model=schemas.StoricoInvestimentoOut)
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

    new_record = models.StoricoInvestimento(**operazione.model_dump())
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record

@app.put("/investimento/operazione/{operazione_id}", response_model=schemas.StoricoInvestimentoOut)
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
    for key, value in operazione_data.model_dump().items():
        setattr(db_operazione, key, value)

    db.commit()
    db.refresh(db_operazione)
    return db_operazione

@app.delete("/investimento/operazione/{operazione_id}", status_code=status.HTTP_204_NO_CONTENT)
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

@app.put("/investimento/{investimento_id}", response_model=schemas.InvestimentoOut)
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

    for key, value in investimento_data.model_dump().items():
        setattr(db_investimento, key, value)

    db.commit()
    db.refresh(db_investimento)
    return db_investimento

@app.delete("/investimento/{investimento_id}", status_code=status.HTTP_204_NO_CONTENT)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")