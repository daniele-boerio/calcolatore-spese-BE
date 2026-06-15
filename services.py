import base64
import os
import time
import requests
import yfinance as yf
from cryptography.fernet import Fernet, InvalidToken
from jose import jwt
from datetime import date, timedelta, datetime, timezone
import logging
from database import SessionLocal
import models
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Query
from sqlalchemy import asc, desc
from pydantic import BaseModel
from decimal import Decimal

# Configura il logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_bank_connector_cipher():
    key = os.getenv("BANK_CONNECTOR_ENCRYPTION_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        try:
            return Fernet(base64.urlsafe_b64encode(key.encode()))
        except Exception:
            logger.warning(
                "Invalid BANK_CONNECTOR_ENCRYPTION_KEY; storing bank tokens without encryption"
            )
            return None


def encrypt_token(value: str) -> str | None:
    if value is None:
        return None
    cipher = get_bank_connector_cipher()
    if cipher:
        return cipher.encrypt(value.encode()).decode()
    return value


def decrypt_token(value: str) -> str | None:
    if value is None:
        return None
    cipher = get_bank_connector_cipher()
    if cipher:
        try:
            return cipher.decrypt(value.encode()).decode()
        except InvalidToken:
            return value
    return value


def get_live_price(ticker_symbol: str, isin_code: str):
    # La logica rimane valida: yfinance preferisce il Ticker, ma l'ISIN è più preciso per i titoli europei
    search_term = ticker_symbol if ticker_symbol else isin_code
    if not search_term:
        return None

    try:
        ticker = yf.Ticker(search_term)
        data = ticker.history(period="1d")

        if not data.empty:
            return Decimal(str(data["Close"].iloc[-1]))

        # Secondo tentativo se il primo fallisce
        if ticker_symbol and isin_code and search_term != isin_code:
            logger.info(f"Ticker {ticker_symbol} fallito, provo con ISIN {isin_code}")
            ticker = yf.Ticker(isin_code)
            data = ticker.history(period="1d")
            if not data.empty:
                return Decimal(str(data["Close"].iloc[-1]))

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

    try:
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
            # Isoliamo ogni ricorrenza: un errore su una non deve bloccare le altre.
            try:
                conto = db.query(models.Conto).get(ric.conto_id)
                if conto is None:
                    logger.warning(
                        "Ricorrenza %s: conto %s inesistente, salto",
                        ric.id,
                        ric.conto_id,
                    )
                    continue

                # 2. Crea la transazione reale
                nuova_trans = models.Transazione(
                    importo=ric.importo,
                    importo_netto=ric.importo,
                    tipo=ric.tipo,
                    descrizione=f"Ricorrente: {ric.nome}",
                    data=today,
                    conto_id=ric.conto_id,
                    user_id=ric.user_id,
                    categoria_id=ric.categoria_id,
                    sottocategoria_id=ric.sottocategoria_id,
                    tag_id=ric.tag_id,
                )

                # 3. Aggiorna il saldo del conto associato
                if str(ric.tipo).upper() == "ENTRATA":
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
                # Commit per-ricorrenza: una riga rotta non perde le altre.
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error("Errore eseguendo la ricorrenza %s: %s", ric.id, e)
    finally:
        db.close()


def task_ricarica_automatica_conti():
    db = SessionLocal()
    today = date.today()

    try:
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
            try:
                # Se il saldo è sceso sotto la soglia minima
                if (
                    conto.soglia_minima is not None
                    and conto.budget_obiettivo is not None
                    and conto.saldo < conto.soglia_minima
                ):
                    importo_ricarica = (
                        conto.budget_obiettivo - conto.saldo
                    ).quantize(Decimal("0.01"))
                    conto_sorgente = db.query(models.Conto).get(
                        conto.conto_sorgente_id
                    )

                    if conto_sorgente and conto_sorgente.saldo >= importo_ricarica:
                        # Giroconto interno: una sola transazione RICARICA dalla
                        # sorgente alla destinazione (esclusa dai totali entrate/uscite).
                        ricarica = models.Transazione(
                            importo=importo_ricarica,
                            importo_netto=importo_ricarica,
                            tipo="RICARICA",
                            descrizione=f"Ricarica automatica da {conto_sorgente.nome}",
                            data=today,
                            conto_id=conto_sorgente.id,
                            conto_destinazione_id=conto.id,
                            user_id=conto.user_id,
                        )
                        db.add(ricarica)

                        # Aggiorna i saldi
                        conto_sorgente.saldo -= importo_ricarica
                        conto.saldo += importo_ricarica

                # 4. Calcola il prossimo controllo
                if conto.frequenza_controllo == "SETTIMANALE":
                    conto.prossimo_controllo = today + timedelta(weeks=1)
                elif conto.frequenza_controllo == "MENSILE":
                    conto.prossimo_controllo = today + relativedelta(months=1)

                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(
                    "Errore nella ricarica automatica del conto %s: %s", conto.id, e
                )
    finally:
        db.close()


def get_nordigen_access_token(client_id: str, secret: str) -> tuple[str, str]:
    url = "https://ob.nordigen.com/api/v2/token/new/"
    payload = {"secret_id": client_id, "secret_key": secret}
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("access"), data.get("refresh")


def refresh_nordigen_access_token(refresh_token: str) -> tuple[str, str]:
    url = "https://ob.nordigen.com/api/v2/token/refresh/"
    payload = {"refresh": refresh_token}
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("access"), data.get("refresh")


# --- Enable Banking Open Banking flow ---
# Auth is app-level: a short-lived JWT (RS256) signed with the application's RSA
# private key, with the application_id carried in the JWT `kid` header. Banks are
# identified by name + country (there is no single institution id).
ENABLE_BANKING_BASE_URL = os.getenv(
    "ENABLE_BANKING_BASE_URL", "https://api.enablebanking.com"
)


def _enable_banking_private_key() -> str:
    path = os.getenv("ENABLE_BANKING_PRIVATE_KEY_PATH")
    if path:
        with open(path, "r") as f:
            return f.read()
    key = os.getenv("ENABLE_BANKING_PRIVATE_KEY")
    if key:
        # Allow the PEM to be stored on a single line with escaped newlines.
        return key.replace("\\n", "\n")
    raise ValueError(
        "Enable Banking private key not configured: set ENABLE_BANKING_PRIVATE_KEY_PATH "
        "or ENABLE_BANKING_PRIVATE_KEY"
    )


def get_enable_banking_jwt() -> str:
    app_id = os.getenv("ENABLE_BANKING_APP_ID")
    if not app_id:
        raise ValueError("Enable Banking is not configured: set ENABLE_BANKING_APP_ID")
    private_key = _enable_banking_private_key()
    now = int(time.time())
    payload = {
        "iss": "enablebanking.com",
        "aud": "api.enablebanking.com",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"typ": "JWT", "kid": app_id},
    )


def _enable_banking_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_enable_banking_jwt()}",
        "Content-Type": "application/json",
    }


def list_enable_banking_aspsps(country: str = "IT") -> list[dict]:
    url = f"{ENABLE_BANKING_BASE_URL}/aspsps"
    response = requests.get(
        url,
        headers=_enable_banking_headers(),
        params={"country": country, "psu_type": "personal"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("aspsps", [])


def start_enable_banking_auth(
    aspsp_name: str,
    aspsp_country: str,
    redirect_url: str,
    state: str,
    valid_days: int = 90,
) -> dict:
    url = f"{ENABLE_BANKING_BASE_URL}/auth"
    valid_until = (
        datetime.now(timezone.utc) + timedelta(days=valid_days)
    ).isoformat()
    payload = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": aspsp_name, "country": aspsp_country},
        "state": state,
        "redirect_url": redirect_url,
        "psu_type": "personal",
    }
    response = requests.post(
        url, headers=_enable_banking_headers(), json=payload, timeout=30
    )
    response.raise_for_status()
    return response.json()


def create_enable_banking_session(code: str) -> dict:
    url = f"{ENABLE_BANKING_BASE_URL}/sessions"
    response = requests.post(
        url, headers=_enable_banking_headers(), json={"code": code}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def fetch_enable_banking_transactions(
    account_uid: str, since: datetime, until: datetime
):
    url = f"{ENABLE_BANKING_BASE_URL}/accounts/{account_uid}/transactions"
    base_params = {
        "date_from": since.date().isoformat(),
        "date_to": until.date().isoformat(),
    }
    transactions = []
    continuation_key = None

    while True:
        params = dict(base_params)
        if continuation_key:
            params["continuation_key"] = continuation_key
        response = requests.get(
            url, headers=_enable_banking_headers(), params=params, timeout=30
        )
        response.raise_for_status()
        payload = response.json()

        for tx in payload.get("transactions", []):
            amount = Decimal(tx.get("transaction_amount", {}).get("amount", "0"))
            if amount == 0:
                continue
            # Berlin Group style: CRDT = incoming, DBIT = outgoing.
            tipo = "ENTRATA" if tx.get("credit_debit_indicator") == "CRDT" else "USCITA"
            amount = abs(amount)
            remittance = tx.get("remittance_information") or []
            descrizione = (
                " ".join(remittance) if isinstance(remittance, list) else remittance
            )
            booking_date = tx.get("booking_date") or tx.get("value_date")
            if booking_date:
                booking_date_obj = datetime.fromisoformat(booking_date).date()
            else:
                booking_date_obj = since.date()
            transactions.append(
                {
                    "external_id": tx.get("entry_reference")
                    or tx.get("transaction_id")
                    or f"{booking_date_obj}-{amount}-{descrizione}",
                    "tipo": tipo,
                    "data": booking_date_obj,
                    "importo": amount,
                    "descrizione": descrizione,
                    "provider": "ENABLEBANKING",
                }
            )

        continuation_key = payload.get("continuation_key")
        if not continuation_key:
            break

    return transactions


def fetch_nordigen_transactions(
    account_id: str, access_token: str, since: datetime, until: datetime
):
    url = f"https://ob.nordigen.com/api/v2/accounts/{account_id}/transactions/"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    params = {
        "date_from": since.date().isoformat(),
        "date_to": until.date().isoformat(),
    }
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    transactions = []

    booked = payload.get("transactions", {}).get("booked", [])
    for tx in booked:
        amount = Decimal(tx.get("transactionAmount", {}).get("amount", "0"))
        if amount == 0:
            continue
        tipo = "USCITA" if amount < 0 else "ENTRATA"
        amount = abs(amount)
        descrizione = tx.get("remittanceInformationUnstructured") or tx.get(
            "remittanceInformationUnstructuredArray", []
        )
        if isinstance(descrizione, list):
            descrizione = " ".join(descrizione)
        descrizione = (
            descrizione
            or tx.get("bookingText")
            or tx.get("creditorName")
            or tx.get("debtorName")
        )
        booking_date = tx.get("bookingDate") or tx.get("valueDate")
        if booking_date:
            booking_date_obj = datetime.fromisoformat(booking_date).date()
        else:
            booking_date_obj = since.date()
        transactions.append(
            {
                "external_id": tx.get("transactionId")
                or tx.get("endToEndId")
                or f"{booking_date_obj}-{amount}-{descrizione}",
                "tipo": tipo,
                "data": booking_date_obj,
                "importo": amount,
                "descrizione": descrizione,
                "provider": "NORDIGEN",
            }
        )
    return transactions


def fetch_bank_transactions_for_conto(db, conto):
    if not conto.bank_connector_provider:
        raise ValueError("Bank connector provider not configured")

    since = conto.bank_connector_last_sync or (datetime.now() - timedelta(days=30))
    until = datetime.now()

    if conto.bank_connector_provider == "ENABLEBANKING":
        if not conto.bank_connector_account_id:
            raise ValueError(
                "Enable Banking connector requires a linked account; complete the bank linking first"
            )
        transactions = fetch_enable_banking_transactions(
            conto.bank_connector_account_id, since, until
        )
        conto.bank_connector_last_sync = datetime.now()
        conto.bank_connector_last_error = None
        db.add(conto)
        db.commit()
        return transactions
    elif conto.bank_connector_provider == "NORDIGEN":
        if (
            not conto.bank_connector_account_id
            or not conto.bank_connector_client_id
            or not conto.bank_connector_secret
        ):
            raise ValueError(
                "Nordigen connector requires account_id, client_id and secret credentials"
            )

        account_id = conto.bank_connector_account_id
        client_id = conto.bank_connector_client_id
        secret = conto.bank_connector_secret
        access_token = decrypt_token(conto.bank_connector_access_token)
        refresh_token = decrypt_token(conto.bank_connector_refresh_token)

        if not access_token:
            access_token, refresh_token = get_nordigen_access_token(client_id, secret)

        try:
            transactions = fetch_nordigen_transactions(
                account_id, access_token, since, until
            )
        except requests.HTTPError as error:
            if (
                error.response is not None
                and error.response.status_code in (401, 403)
                and refresh_token
            ):
                access_token, refresh_token = refresh_nordigen_access_token(
                    refresh_token
                )
                transactions = fetch_nordigen_transactions(
                    account_id, access_token, since, until
                )
            else:
                raise

        if access_token:
            conto.bank_connector_access_token = encrypt_token(access_token)
        if refresh_token:
            conto.bank_connector_refresh_token = encrypt_token(refresh_token)

        conto.bank_connector_last_sync = datetime.now()
        conto.bank_connector_last_error = None
        db.add(conto)
        db.commit()
        return transactions
    elif conto.bank_connector_provider == "MOCK":
        return [
            {
                "external_id": f"mock-{i}-{since.date()}",
                "provider": "MOCK",
                "tipo": "USCITA",
                "data": since.date(),
                "importo": Decimal("10.00") * (i + 1),
                "descrizione": f"Mock bank transaction {i + 1}",
            }
            for i in range(3)
        ]
    else:
        raise ValueError(
            f"Unsupported bank connector provider: {conto.bank_connector_provider}"
        )


def create_bank_transaction_proposal(db, user_id, conto, candidate):
    if candidate.get("external_id"):
        existing = (
            db.query(models.BankTransactionProposal)
            .filter(
                models.BankTransactionProposal.user_id == user_id,
                models.BankTransactionProposal.conto_id == conto.id,
                models.BankTransactionProposal.provider == candidate.get("provider"),
                models.BankTransactionProposal.external_id
                == candidate.get("external_id"),
            )
            .first()
        )
        if existing:
            return None

    duplicate = (
        db.query(models.BankTransactionProposal)
        .filter(
            models.BankTransactionProposal.user_id == user_id,
            models.BankTransactionProposal.conto_id == conto.id,
            models.BankTransactionProposal.data == candidate.get("data"),
            models.BankTransactionProposal.importo == candidate.get("importo"),
            models.BankTransactionProposal.descrizione == candidate.get("descrizione"),
            models.BankTransactionProposal.status != "DISCARDED",
        )
        .first()
    )
    if duplicate:
        return None

    proposal = models.BankTransactionProposal(
        user_id=user_id,
        conto_id=conto.id,
        provider=candidate.get("provider"),
        external_id=candidate.get("external_id"),
        tipo=candidate.get("tipo"),
        data=candidate.get("data"),
        importo=candidate.get("importo"),
        descrizione=candidate.get("descrizione"),
        status="PENDING",
    )
    db.add(proposal)
    return proposal


def import_bank_transaction_proposal(db, proposal, import_data, current_user_id):
    from datetime import date
    from models import Transazione, Conto, Categoria, Sottocategoria

    conto = db.query(Conto).filter(Conto.id == proposal.conto_id).first()
    if not conto:
        raise ValueError("Associated account not found")

    tipo = proposal.tipo
    importo = proposal.importo
    if tipo not in ["USCITA", "ENTRATA", "RIMBORSO"]:
        tipo = "USCITA"

    new_trans = Transazione(
        importo=importo,
        importo_netto=importo,
        tipo=tipo,
        data=proposal.data,
        descrizione=import_data.descrizione or proposal.descrizione,
        conto_id=proposal.conto_id,
        user_id=current_user_id,
        categoria_id=import_data.categoria_id,
        sottocategoria_id=import_data.sottocategoria_id,
        tag_id=import_data.tag_id,
    )

    modifier = Decimal("-1") if tipo == "USCITA" else Decimal("1")
    conto.saldo += importo * modifier

    db.add(new_trans)
    db.flush()

    proposal.status = "IMPORTED"
    proposal.imported_transaction_id = new_trans.id
    db.add(conto)
    db.add(proposal)
    return new_trans


def task_sync_bank_connectors():
    db = SessionLocal()
    try:
        conti = (
            db.query(models.Conto)
            .filter(models.Conto.bank_connector_provider != None)
            .all()
        )

        for conto in conti:
            try:
                candidates = fetch_bank_transactions_for_conto(db, conto)
                proposals_created = 0
                for candidate in candidates:
                    if create_bank_transaction_proposal(
                        db, conto.user_id, conto, candidate
                    ):
                        proposals_created += 1
                if proposals_created:
                    logger.info(
                        f"Bank sync for conto {conto.id}: created {proposals_created} proposals"
                    )
            except Exception as e:
                conto.bank_connector_last_error = str(e)
                db.add(conto)
                db.commit()
                logger.error(f"Bank sync failed for conto {conto.id}: {e}")
                continue

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Fatal error in task_sync_bank_connectors: {e}")
    finally:
        db.close()


def discard_bank_transaction_proposal(db, proposal):
    proposal.status = "DISCARDED"
    db.add(proposal)
    return proposal


def apply_filters_and_sort(query: Query, model, filters):
    # Supporta sia BaseModel di Pydantic che classi standard con model_dump()
    filter_data = (
        filters.model_dump() if hasattr(filters, "model_dump") else filters.dict()
    )

    sort_by = filter_data.pop("sort_by", None)

    for field, value in filter_data.items():
        if value is None:
            continue

        # 1. Gestione LISTE e SINGOLI VALORI (Clausola IN)
        # Se il valore è una lista o un intero per i campi ID
        if field in ["conto_id", "categoria_id", "sottocategoria_id", "tag_id"]:
            if hasattr(model, field):
                column = getattr(model, field)
                # Normalizziamo a lista se è un singolo valore
                if not isinstance(value, list):
                    value = [value]
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

    # Ordinamento Multi-campo Avanzato
    if sort_by:
        sort_fields = sort_by if isinstance(sort_by, list) else [sort_by]
        order_clauses = []

        for item in sort_fields:
            # Supportiamo il formato "campo:ordine" (es. "data:desc")
            if ":" in item:
                field, order = item.split(":", 1)
            else:
                field, order = item, "asc"  # Default se non specificato

            if hasattr(model, field):
                column = getattr(model, field)
                clause = desc(column) if order.lower() == "desc" else asc(column)
                order_clauses.append(clause)

        if order_clauses:
            query = query.order_by(*order_clauses)
    elif hasattr(model, "id"):
        query = query.order_by(desc(model.id))

    return query
