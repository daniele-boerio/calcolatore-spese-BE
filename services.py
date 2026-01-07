import yfinance as yf
from datetime import date
import logging
from database import SessionLocal
import models

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