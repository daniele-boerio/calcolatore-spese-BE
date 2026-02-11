import yfinance as yf
from datetime import date, timedelta, datetime
import logging
from database import SessionLocal
import models
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Query
from sqlalchemy import asc, desc
from pydantic import BaseModel

# Configura il logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_live_price(ticker_symbol: str, isin_code: str):
    # La logica rimane valida: yfinance preferisce il Ticker, ma l'ISIN è più preciso per i titoli europei
    search_term = ticker_symbol if ticker_symbol else isin_code
    if not search_term:
        return None

    try:
        ticker = yf.Ticker(search_term)
        data = ticker.history(period="1d")

        if not data.empty:
            return float(data["Close"].iloc[-1])

        # Secondo tentativo se il primo fallisce
        if ticker_symbol and isin_code and search_term != isin_code:
            logger.info(f"Ticker {ticker_symbol} fallito, provo con ISIN {isin_code}")
            ticker = yf.Ticker(isin_code)
            data = ticker.history(period="1d")
            if not data.empty:
                return float(data["Close"].iloc[-1])

        logger.warning(f"Nessun dato trovato per {search_term}")
        return None

    except Exception as e:
        logger.error(f"Errore critico durante yfinance per {search_term}: {str(e)}")
        return None


def task_aggiornamento_prezzi():
    """
    Questo task aggiorna solo il campo 'prezzo_attuale' nell'anagrafica Investimento.
    I calcoli di profitto e valore totale verranno fatti al volo dalle @property del modello.
    """
    logger.info("Avvio task aggiornamento prezzi investimenti...")
    db = SessionLocal()
    try:
        # Recuperiamo solo i titoli che hanno un ticker o un ISIN
        investimenti = db.query(models.Investimento).all()

        for inv in investimenti:
            try:
                prezzo_live = get_live_price(inv.ticker, inv.isin)

                if prezzo_live:
                    inv.prezzo_attuale = prezzo_live
                    inv.data_ultimo_aggiornamento = date.today()

                    # OPZIONALE: Se vuoi loggare il profitto attuale usando la @property:
                    logger.info(
                        f"{inv.nome_titolo}: Prezzo {prezzo_live} - P&L: {inv.valore_posizione - (inv.quantita_totale * inv.prezzo_medio_carico)}"
                    )

                    logger.info(
                        f"Aggiornato {inv.nome_titolo or inv.isin}: {prezzo_live}"
                    )
                else:
                    logger.warning(
                        f"Impossibile trovare prezzo live per {inv.nome_titolo or inv.isin}"
                    )

            except Exception as e:
                logger.error(f"Errore durante l'aggiornamento del titolo {inv.id}: {e}")
                continue

        db.commit()
        logger.info("Task aggiornamento prezzi completato.")
    except Exception as e:
        db.rollback()
        logger.error(f"Errore fatale nel task investimenti: {e}")
    finally:
        db.close()


def task_transazioni_ricorrenti():
    db = SessionLocal()
    today = date.today()

    # 1. Trova tutte le ricorrenze attive che devono essere eseguite oggi o prima
    ricorrenze = (
        db.query(models.Ricorrenza)
        .filter(
            models.Ricorrenza.attiva,
            models.Ricorrenza.prossima_esecuzione <= today,
        )
        .all()
    )

    for ric in ricorrenze:
        # 2. Crea la transazione reale
        nuova_trans = models.Transazione(
            importo=ric.importo,
            tipo=ric.tipo,
            descrizione=f"Ricorrente: {ric.nome}",
            data=datetime.now(),
            conto_id=ric.conto_id,
            user_id=ric.user_id,
            categoria_id=ric.categoria_id,
            sottocategoria_id=ric.sottocategoria_id,
            tag_id=ric.tag_id,
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


def task_ricarica_automatica_conti():
    db = SessionLocal()
    today = date.today()

    # Trova i conti con ricarica attiva che devono essere controllati oggi
    conti_da_controllare = (
        db.query(models.Conto)
        .filter(
            models.Conto.ricarica_automatica,
            models.Conto.prossimo_controllo <= today,
        )
        .all()
    )

    for conto in conti_da_controllare:
        # Se il saldo è sceso sotto la soglia minima
        if conto.saldo < conto.soglia_minima:
            importo_ricarica = conto.budget_obiettivo - conto.saldo
            conto_sorgente = db.query(models.Conto).get(conto.conto_sorgente_id)

            if conto_sorgente and conto_sorgente.saldo >= importo_ricarica:
                # 1. Crea la transazione di uscita dal conto sorgente
                uscita = models.Transazione(
                    importo=importo_ricarica,
                    tipo="USCITA",
                    descrizione=f"Ricarica automatica verso {conto.nome}",
                    data=datetime.now(),
                    conto_id=conto_sorgente.id,
                )
                # 2. Crea la transazione di entrata nel conto target
                entrata = models.Transazione(
                    importo=importo_ricarica,
                    tipo="ENTRATA",
                    descrizione=f"Ricarica automatica da {conto_sorgente.nome}",
                    data=datetime.now(),
                    conto_id=conto.id,
                )

                # Aggiorna i saldi
                conto_sorgente.saldo -= importo_ricarica
                conto.saldo += importo_ricarica

                db.add(uscita)
                db.add(entrata)

        # 4. Calcola il prossimo controllo
        if conto.frequenza_controllo == "SETTIMANALE":
            conto.prossimo_controllo = today + timedelta(weeks=1)
        elif conto.frequenza_controllo == "MENSILE":
            conto.prossimo_controllo = today + relativedelta(months=1)

    db.commit()
    db.close()


def apply_filters_and_sort(query: Query, model, filters: BaseModel):
    filter_data = filters.model_dump(exclude_unset=True)
    sort_by = filter_data.pop("sort_by", None)
    sort_order = filter_data.pop("sort_order", "asc")

    for field, value in filter_data.items():
        if value is None:
            continue

        # 1. Gestione LISTE (Clausola IN)
        # Se il valore è una lista, usiamo .in_() per filtrare più ID contemporaneamente
        if isinstance(value, list) and hasattr(model, field):
            column = getattr(model, field)
            query = query.filter(column.in_(value))

        # 2. Gestione Range Importo (_min / _max)
        elif field.endswith("_min") and hasattr(model, field.replace("_min", "")):
            column = getattr(model, field.replace("_min", ""))
            query = query.filter(column >= value)
        elif field.endswith("_max") and hasattr(model, field.replace("_max", "")):
            column = getattr(model, field.replace("_max", ""))
            query = query.filter(column <= value)

        # 3. Gestione Range Date (_inizio / _fine)
        elif field.endswith("_inizio") and hasattr(model, field.replace("_inizio", "")):
            column = getattr(model, field.replace("_inizio", ""))
            query = query.filter(column >= value)
        elif field.endswith("_fine") and hasattr(model, field.replace("_fine", "")):
            column = getattr(model, field.replace("_fine", ""))
            query = query.filter(column <= value)

        # 4. Ricerca parziale (LIKE)
        elif field in [
            "nome",
            "descrizione",
            "nome_titolo",
        ] and hasattr(model, field):
            column = getattr(model, field)
            query = query.filter(column.ilike(f"%{value}%"))

        # 5. Uguaglianza standard per gli altri campi singoli
        elif hasattr(model, field):
            query = query.filter(getattr(model, field) == value)

    # Ordinamento
    if sort_by and hasattr(model, sort_by):
        order_func = desc if sort_order.lower() == "desc" else asc
        query = query.order_by(order_func(getattr(model, sort_by)))
    elif hasattr(model, "id"):
        query = query.order_by(desc(model.id))

    return query
