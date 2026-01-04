import yfinance as yf
from datetime import date
from database import SessionLocal
import models

def get_live_price(ticker_symbol: str, isin_code: str):
    # Prova prima con il Ticker (più affidabile per yfinance)
    # Se il ticker non c'è, usa l'ISIN
    search_term = ticker_symbol if ticker_symbol else isin_code
    
    try:
        ticker = yf.Ticker(search_term)
        data = ticker.history(period="1d")
        
        if not data.empty:
            return data['Close'].iloc[-1]
        
        # Se fallisce col ticker, prova un ultimo tentativo con l'ISIN
        if ticker_symbol and isin_code:
            ticker = yf.Ticker(isin_code)
            data = ticker.history(period="1d")
            if not data.empty:
                return data['Close'].iloc[-1]
                
        return None
    except Exception as e:
        print(f"Errore ricerca per {search_term}: {e}")
        return None
    
def task_aggiornamento_prezzi():
    db = SessionLocal()
    try:
        investimenti = db.query(models.Investimento).all()
        for inv in investimenti:
            # Passiamo sia ticker che isin
            prezzo_live = get_live_price(inv.ticker, inv.isin)
            if prezzo_live:
                inv.prezzo_attuale = prezzo_live
                inv.data_ultimo_aggiornamento = date.today()
        db.commit()
    finally:
        db.close()