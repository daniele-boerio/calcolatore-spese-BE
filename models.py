from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean, Date
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base
from sqlalchemy.orm import relationship, backref

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=False, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    
    # Relazioni
    conti = relationship("Conto", back_populates="owner", cascade="all, delete-orphan")
    categorie = relationship("Categoria", back_populates="owner", cascade="all, delete-orphan")
    investimenti = relationship("Investimento", cascade="all, delete-orphan")

class Conto(Base):
    __tablename__ = "conti"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False) # es. Contanti, Intesa, Revolut
    user_id = Column(Integer, ForeignKey("users.id"))
    
    owner = relationship("User", back_populates="conti")
    transazioni = relationship("Transazione", back_populates="conto", cascade="all, delete-orphan")

class Categoria(Base):
    __tablename__ = "categorie"
    
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Se questo è NULL, è una categoria principale. 
    # Se contiene un ID, è una sottocategoria.
    parent_id = Column(Integer, ForeignKey("categorie.id"), nullable=True)
    
    # Relazioni
    owner = relationship("User", back_populates="categorie")
    
    # Questa riga crea la gerarchia
    subcategorie = relationship(
        "Categoria", 
        backref=backref('parent', remote_side=[id]),
        cascade="all, delete-orphan" # Se cancelli il padre, cancella le sottocategorie
    )

class Transazione(Base):
    __tablename__ = "transazioni"
    id = Column(Integer, primary_key=True, index=True)
    importo = Column(Float, nullable=False)
    tipo = Column(String, nullable=False) # "ENTRATA" o "USCITA"
    data = Column(DateTime, default=datetime.utcnow)
    descrizione = Column(String)
    
    conto_id = Column(Integer, ForeignKey("conti.id", ondelete="CASCADE"))
    categoria_id = Column(Integer, ForeignKey("categorie.id", ondelete="SET NULL"), nullable=True)
    
    conto = relationship("Conto", back_populates="transazioni")

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
    
    storico = relationship("StoricoInvestimento", back_populates="investimento")

class StoricoInvestimento(Base):
    __tablename__ = "storico_investimenti"
    id = Column(Integer, primary_key=True, index=True)
    investimento_id = Column(Integer, ForeignKey("investimenti.id", ondelete="CASCADE"))
    data = Column(Date, nullable=False)
    quantita = Column(Float) # Positiva per acquisto, negativa per vendita
    prezzo_unitario = Column(Float)
    valore_attuale = Column(Float) # Per tracciare l'andamento nel tempo
    investimento = relationship("Investimento", back_populates="storico")