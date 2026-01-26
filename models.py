from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean, Date, Table
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base
from sqlalchemy.orm import relationship, backref

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=False, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    total_budget = Column(Float, nullable=True) # Per la BudgetCard

    conti = relationship("Conto", cascade="all, delete-orphan", order_by="desc(Conto.creationDate), desc(Conto.lastUpdate), Conto.id")
    investimenti = relationship("Investimento", cascade="all, delete-orphan", order_by="desc(Investimento.creationDate), desc(Investimento.lastUpdate), Investimento.id")
    
    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Conto(Base):
    __tablename__ = "conti"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    saldo = Column(Float, nullable=False, default=0.0) # Saldo dinamico

    # --- Nuovi campi per Satispay-style ---
    ricarica_automatica = Column(Boolean, default=False)
    budget_obiettivo = Column(Float, nullable=True)  # Il valore a cui deve tornare il saldo
    soglia_minima = Column(Float, nullable=True)    # Il valore sotto il quale scatta la ricarica
    conto_sorgente_id = Column(Integer, ForeignKey("conti.id"), nullable=True) # Da dove prendiamo i soldi
    frequenza_controllo = Column(String, nullable=True) # "SETTIMANALE" o "MENSILE"
    prossimo_controllo = Column(Date, nullable=True)    # Quando effettuare il prossimo check

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    
    transazioni = relationship("Transazione", cascade="all, delete-orphan", order_by="desc(Transazione.data), desc(Transazione.creationDate), desc(Transazione.lastUpdate), Transazione.id")

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Categoria(Base):
    __tablename__ = "categorie"
    
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    
    # Una categoria ha più sottocategorie
    sottocategorie = relationship("Sottocategoria", cascade="all, delete-orphan", order_by="Sottocategoria.creationDate, Sottocategoria.lastUpdate, Sottocategoria.id")

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Sottocategoria(Base):
    __tablename__ = "sottocategorie"
    
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    # Si riferisce a una sola categoria
    categoria_id = Column(Integer, ForeignKey("categorie.id", ondelete="CASCADE"))

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    
    # Si riferisce a diverse transazioni
    transazioni = relationship("Transazione", order_by="desc(Transazione.data), desc(Transazione.creationDate), desc(Transazione.lastUpdate), Transazione.id")

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Transazione(Base):
    __tablename__ = "transazioni"
    id = Column(Integer, primary_key=True, index=True)
    importo = Column(Float, nullable=False)
    tipo = Column(String, nullable=False) # "ENTRATA", "USCITA" o "RIMBORSO"
    data = Column(DateTime)
    descrizione = Column(String)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    conto_id = Column(Integer, ForeignKey("conti.id", ondelete="CASCADE"))
    categoria_id = Column(Integer, ForeignKey("categorie.id", ondelete="SET NULL"), nullable=True)
    sottocategoria_id = Column(Integer, ForeignKey("sottocategorie.id", ondelete="SET NULL"), nullable=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)
    
    # per i rimborsi, collega la transazione al padre
    parent_transaction_id = Column(
        Integer, 
        ForeignKey("transazioni.id", ondelete="CASCADE"), 
        nullable=True
    )

    # Relazioni
    categoria = relationship("Categoria", order_by="desc(Categoria.creationDate), desc(Categoria.lastUpdate), Categoria.id")
    sottocategoria = relationship("Sottocategoria", order_by="desc(Sottocategoria.creationDate), desc(Sottocategoria.lastUpdate), Sottocategoria.id")

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Investimento(Base):
    __tablename__ = "investimenti"
    id = Column(Integer, primary_key=True, index=True)
    isin = Column(String, index=True, nullable=False)
    ticker = Column(String, index=True, nullable=True)
    nome_titolo = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Questi campi vengono SOVRASCRITTI ogni notte, non creano nuovi record
    prezzo_attuale = Column(Float, nullable=True)
    data_ultimo_aggiornamento = Column(Date, nullable=True)

    storico = relationship("StoricoInvestimento", cascade="all, delete-orphan", order_by="desc(StoricoInvestimento.creationDate), desc(StoricoInvestimento.lastUpdate), StoricoInvestimento.id")

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class StoricoInvestimento(Base):
    __tablename__ = "storico_investimenti"
    id = Column(Integer, primary_key=True, index=True)
    investimento_id = Column(Integer, ForeignKey("investimenti.id", ondelete="CASCADE"))
    data = Column(Date, nullable=False)
    quantita = Column(Float) # Positiva per acquisto, negativa per vendita
    prezzo_unitario = Column(Float)
    valore_attuale = Column(Float) # Per tracciare l'andamento nel tempo

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )

class Ricorrenza(Base):
    __tablename__ = "ricorrenze"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False) # Es: "Affitto", "Netflix"
    importo = Column(Float, nullable=False)
    tipo = Column(String, nullable=False) # ENTRATA o USCITA
    frequenza = Column(String, nullable=False) # GIORNALIERA, SETTIMANALE, MENSILE, ANNUALE
    prossima_esecuzione = Column(Date, nullable=False) # La data in cui dovrà scattare
    attiva = Column(Boolean, default=True)

    # Chiavi esterne (template per la transazione futura)
    user_id = Column(Integer, ForeignKey("users.id"))
    conto_id = Column(Integer, ForeignKey("conti.id"))
    categoria_id = Column(Integer, ForeignKey("categorie.id", ondelete="SET NULL"), nullable=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), nullable=True)

    creationDate = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastUpdate = Column(
        DateTime, 
        default=lambda: datetime.now(timezone.utc), 
        onupdate=lambda: datetime.now(timezone.utc)
    )