import yfinance as yf
from datetime import date, timedelta, datetime
import logging
from database import SessionLocal
import models
from dateutil.relativedelta import relativedelta

# Configura il logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_live_price(ticker_symbol: str, isin_code: str):
    search_term = ticker_symbol if ticker_symbol else isin_code
    if not search_term:
        return None
    
    try:
        # Usiamo un timeout per evitare che yfinance rimanga appeso troppo a lungo
        ticker = yf.Ticker(search_term)
        data = ticker.history(period="1d")
        
        if not data.empty:
            return float(data['Close'].iloc[-1])
        
        # Secondo tentativo se il primo fallisce
        if ticker_symbol and isin_code and search_term != isin_code:
            logger.info(f"Ticker {ticker_symbol} fallito, provo con ISIN {isin_code}")
            ticker = yf.Ticker(isin_code)
            data = ticker.history(period="1d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
                
        logger.warning(f"Nessun dato trovato per {search_term}")
        return None

    except Exception as e:
        logger.error(f"Errore critico durante yfinance per {search_term}: {str(e)}")
        return None
    
def task_aggiornamento_prezzi():
    logger.info("Avvio task aggiornamento prezzi...")
    db = SessionLocal()
    try:
        investimenti = db.query(models.Investimento).all()
        for inv in investimenti:
            try:
                prezzo_live = get_live_price(inv.ticker, inv.isin)
                if prezzo_live:
                    inv.prezzo_attuale = prezzo_live
                    inv.data_ultimo_aggiornamento = date.today()
                    logger.info(f"Aggiornato {inv.nome_titolo or inv.ticker}: {prezzo_live}")
                else:
                    logger.warning(f"Impossibile aggiornare {inv.nome_titolo or inv.ticker}")
            except Exception as e:
                # Questo try/except interno evita che il fallimento di UN titolo 
                # blocchi il ciclo for per gli altri titoli
                logger.error(f"Errore durante l'aggiornamento di {inv.id}: {e}")
                continue 

        db.commit()
        logger.info("Task completato con successo.")
    except Exception as e:
        db.rollback() # Se succede qualcosa di grave al DB, annulla le modifiche
        logger.error(f"Errore fatale nel task: {e}")
    finally:
        db.close()

def task_transazioni_ricorrenti():
    db = SessionLocal()
    today = date.today()
    
    # 1. Trova tutte le ricorrenze attive che devono essere eseguite oggi o prima
    ricorrenze = db.query(models.Ricorrenza).filter(
        models.Ricorrenza.attiva == True,
        models.Ricorrenza.prossima_esecuzione <= today
    ).all()

    for ric in ricorrenze:
        # 2. Crea la transazione reale
        nuova_trans = models.Transazione(
            importo=ric.importo,
            tipo=ric.tipo,
            descrizione=f"Ricorrente: {ric.nome}",
            data=datetime.combine(ric.prossima_esecuzione, datetime.min.time()),
            conto_id=ric.conto_id,
            categoria_id=ric.categoria_id,
            tag_id=ric.tag_id
        )
        
        # 3. Aggiorna il saldo del conto associato
        conto = db.query(models.Conto).get(ric.conto_id)
        if ric.tipo.upper() == "ENTRATA":
            conto.saldo += ric.importo
        else:
            conto.saldo -= ric.importo

        # 4. Calcola la prossima data di esecuzione
        if ric.frequenza == "GIORNALIERA":
            ric.prossima_esecuzione += timedelta(days=1)
        elif ric.frequenza == "SETTIMANALE":
            ric.prossima_esecuzione += timedelta(weeks=1)
        elif ric.frequenza == "MENSILE":
            ric.prossima_esecuzione += relativedelta(months=1)
        elif ric.frequenza == "ANNUALE":
            ric.prossima_esecuzione += relativedelta(years=1)

        db.add(nuova_trans)
    
    db.commit()
    db.close()