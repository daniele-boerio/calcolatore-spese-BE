import base64
import io
import os
import re
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
from decimal import Decimal, InvalidOperation
from typing import Optional

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

                # Conto in soft-delete: la ricorrenza resta sospesa finché il conto
                # non viene ripristinato (niente transazioni fantasma su un conto nascosto).
                if conto.deleted_at is not None:
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
                models.Conto.deleted_at.is_(None),
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

                    if (
                        conto_sorgente
                        and conto_sorgente.deleted_at is None
                        and conto_sorgente.saldo >= importo_ricarica
                    ):
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

    # Conto di destinazione: l'utente può sceglierne uno diverso da quello della
    # proposta (default = conto della proposta). Dev'essere comunque suo.
    target_conto_id = getattr(import_data, "conto_id", None) or proposal.conto_id
    conto = (
        db.query(Conto)
        .filter(
            Conto.id == target_conto_id,
            Conto.user_id == current_user_id,
            Conto.deleted_at.is_(None),
        )
        .first()
    )
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
        # La descrizione la decide l'utente: non ripieghiamo su quella della banca
        descrizione=import_data.descrizione,
        conto_id=conto.id,
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
            .filter(
                models.Conto.bank_connector_provider != None,
                models.Conto.deleted_at.is_(None),
            )
            .all()
        )

        for conto in conti:
            # Evitiamo chiamate ravvicinate (rate limit PSD2 / 429): se il conto
            # è stato sincronizzato da meno di ~5 ore, lo saltiamo in questo giro.
            last = conto.bank_connector_last_sync
            if last is not None:
                # last_sync può essere naive o aware a seconda di chi l'ha scritto
                last_naive = last.replace(tzinfo=None)
                if datetime.now() - last_naive < timedelta(hours=5):
                    continue

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


# --- Import estratto conto PDF -> proposte di transazione -------------------
#
# Parser locale (nessun servizio esterno). L'euristica è volutamente GENERICA:
# ogni banca ha un layout diverso e non tentiamo di riconoscerle tutte. Le
# transazioni estratte diventano proposte PENDING che l'utente rivede una a una
# prima dell'import, quindi l'obiettivo è un baseline ragionevole, facile da
# ritarare (vedi il parametro `balance_column`).

# Importi in formato italiano: 1.234,56 / 12,00 / -45,90 / 1.234,56- (segno in coda)
_AMOUNT_RE = re.compile(r"[-+]?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}-?")
# Date: 01/02/2026, 01-02-26, 01.02.2026
_DATE_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
# Data a inizio riga: segnala l'inizio di un nuovo movimento.
_DATE_START_RE = re.compile(r"^\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b")
# Cap di righe accumulabili in un singolo movimento multi-riga (anti-runaway).
_MAX_RECORD_LINES = 8
# Righe che NON sono movimenti (intestazioni, riepiloghi, piè di pagina...)
_SKIP_HINTS = (
    "saldo",
    "riepilogo",
    "totale",
    "data valuta",
    "descrizione operazione",
    "estratto conto",
    "pagina",
    "iban",
    "intestaz",
)


def _parse_italian_amount(token: str) -> Optional[Decimal]:
    """"1.234,56" / "-45,90" / "12,00-" -> Decimal. None se non parsabile."""
    t = token.strip()
    negative = False
    if t.endswith("-"):
        negative = True
        t = t[:-1]
    if t.startswith("-"):
        negative = True
        t = t[1:]
    elif t.startswith("+"):
        t = t[1:]
    t = t.replace(".", "").replace(",", ".")
    try:
        value = Decimal(t)
    except InvalidOperation:
        return None
    return -value if negative else value


def _parse_statement_date(day: str, month: str, year: str) -> Optional[date]:
    try:
        d, m, y = int(day), int(month), int(year)
    except ValueError:
        return None
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _record_to_movimento(
    text: str,
    data_da: Optional[date],
    data_a: Optional[date],
    balance_column: bool,
) -> Optional[dict]:
    """Trasforma il testo di UN movimento (anche accorpato da più righe) in un
    candidato proposta. None se non contiene data+importo validi."""
    date_match = _DATE_RE.search(text)
    if not date_match:
        return None
    data = _parse_statement_date(*date_match.groups())
    if data is None:
        return None

    amount_tokens = _AMOUNT_RE.findall(text)
    parsed_amounts = [(_parse_italian_amount(tok), tok) for tok in amount_tokens]
    parsed_amounts = [(v, tok) for v, tok in parsed_amounts if v is not None]
    if not parsed_amounts:
        return None

    # Se la banca stampa anche il saldo progressivo, l'importo del movimento è
    # il penultimo numero della riga (l'ultimo è il saldo).
    if balance_column and len(parsed_amounts) >= 2:
        importo_val, _ = parsed_amounts[-2]
    else:
        importo_val, _ = parsed_amounts[-1]

    importo = abs(importo_val)
    if importo == 0:
        return None

    if (data_da and data < data_da) or (data_a and data > data_a):
        return None

    # Descrizione = testo tra la data e il primo importo.
    first_amount_pos = text.find(amount_tokens[0], date_match.end())
    if first_amount_pos == -1:
        first_amount_pos = len(text)
    descrizione = text[date_match.end() : first_amount_pos].strip(" \t-–—.€")
    if not descrizione:
        descrizione = text[date_match.end() :].strip(" \t-–—.€")
    # Se in testa resta una seconda data (la "valuta"), la togliamo.
    lead_date = _DATE_RE.match(descrizione)
    if lead_date:
        descrizione = descrizione[lead_date.end() :].strip(" \t-–—.€")
    # Toglie una valuta rimasta in coda (es. "... Altre uscite €" / "EUR").
    descrizione = re.sub(r"\s*(?:€|eur|usd)\s*$", "", descrizione, flags=re.IGNORECASE)
    descrizione = re.sub(r"\s+", " ", descrizione).strip()

    return {
        "provider": "PDF",
        "external_id": None,
        "tipo": "USCITA" if importo_val < 0 else "ENTRATA",
        "data": data,
        "importo": importo,
        "descrizione": descrizione or None,
    }


def parse_statement_text(
    text: str,
    data_da: Optional[date] = None,
    data_a: Optional[date] = None,
    balance_column: bool = False,
) -> list[dict]:
    """Estrae i movimenti dal testo grezzo di un estratto conto.

    Un movimento INIZIA a una riga che parte con una data e si chiude quando
    incontra un importo in formato italiano, anche parecchie righe più sotto:
    molte banche (es. ISYBANK) mandano a capo le celle (categoria, descrizione)
    così data e importo finiscono su righe diverse. Accorpiamo quindi le righe
    in "record" invece di trattarle una per una. Il tipo si deduce dal segno
    dell'importo (negativo -> USCITA, positivo -> ENTRATA).

    Funzione pura (nessun I/O): testabile con testo di esempio senza PDF.
    """
    movimenti: list[dict] = []
    buffer: list[str] = []

    def flush_if_complete() -> bool:
        nonlocal buffer
        joined = " ".join(buffer)
        if _AMOUNT_RE.search(joined):
            mov = _record_to_movimento(joined, data_da, data_a, balance_column)
            if mov:
                movimenti.append(mov)
            buffer = []
            return True
        return False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        is_date_start = _DATE_START_RE.match(line) is not None

        # Righe di intestazione/riepilogo (saldo, totale...) ignorate SOLO se non
        # stiamo già componendo un movimento multi-riga.
        if not buffer and not is_date_start and any(h in low for h in _SKIP_HINTS):
            continue

        if is_date_start:
            # Nuovo movimento: se in buffer c'era un record non chiuso, era
            # rumore d'intestazione (nessun importo) e viene scartato.
            buffer = [line]
            flush_if_complete()  # se la riga contiene già l'importo, chiude subito
        elif buffer:
            buffer.append(line)
            if not flush_if_complete() and len(buffer) > _MAX_RECORD_LINES:
                buffer = []
        # else: fuori da un movimento -> riga ignorata

    return movimenti


def extract_pdf_text(file_bytes: bytes) -> str:
    """Estrae tutto il testo da un PDF (import locale via pdfplumber)."""
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def parse_bank_statement_pdf(
    file_bytes: bytes,
    data_da: Optional[date] = None,
    data_a: Optional[date] = None,
    balance_column: bool = False,
) -> list[dict]:
    """PDF (bytes) -> lista di candidati proposta {provider, tipo, data, importo, descrizione}."""
    text = extract_pdf_text(file_bytes)
    return parse_statement_text(
        text, data_da=data_da, data_a=data_a, balance_column=balance_column
    )


# --- Import estratto conto Excel/CSV -> proposte -----------------------------
#
# Molto più affidabile del PDF: l'export a foglio di calcolo ha colonne pulite.
# Individuiamo l'intestazione dai nomi delle colonne e mappiamo data / importo /
# descrizione, senza euristiche di layout.

# Parole chiave (in minuscolo) per riconoscere le colonne nell'intestazione.
_COL_DESCR = ("operazione", "descrizione", "causale", "dettaglio")
_COL_ENTRATE = ("entrate", "accrediti", "avere")
_COL_USCITE = ("uscite", "addebiti", "dare")


def _coerce_date(value) -> Optional[date]:
    """Cella -> date. Gestisce datetime/date nativi (Excel) e stringhe."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = _DATE_RE.search(str(value))
    if match:
        return _parse_statement_date(*match.groups())
    return None


def _coerce_amount(value) -> Optional[Decimal]:
    """Cella -> Decimal. Gestisce numeri nativi (Excel) e stringhe italiane."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value)
    match = _AMOUNT_RE.search(text)
    if match:
        return _parse_italian_amount(match.group(0))
    # Fallback: formato con punto decimale (es. "-30.00") o solo cifre.
    cleaned = text.strip().replace("€", "").replace(" ", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _cell(row: list, idx: Optional[int]):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _detect_columns(header: list) -> Optional[dict]:
    """Dato l'elenco delle intestazioni, ritorna gli indici di data/descrizione/
    importo (o entrate+uscite). None se la riga non è un'intestazione valida."""
    norm = [str(c or "").strip().lower() for c in header]
    cols = {
        "date": None,
        "descr": None,
        "amount": None,
        "entrate": None,
        "uscite": None,
    }
    for i, h in enumerate(norm):
        if cols["date"] is None and "data" in h:
            cols["date"] = i
        if cols["descr"] is None and any(k in h for k in _COL_DESCR):
            cols["descr"] = i
        if cols["amount"] is None and "importo" in h:
            cols["amount"] = i
        if cols["entrate"] is None and any(k in h for k in _COL_ENTRATE):
            cols["entrate"] = i
        if cols["uscite"] is None and any(k in h for k in _COL_USCITE):
            cols["uscite"] = i
    has_amount = (
        cols["amount"] is not None
        or cols["entrate"] is not None
        or cols["uscite"] is not None
    )
    if cols["date"] is None or not has_amount:
        return None
    return cols


def parse_statement_rows(
    rows: list,
    provider: str = "IMPORT",
    data_da: Optional[date] = None,
    data_a: Optional[date] = None,
) -> list[dict]:
    """Righe (liste di celle grezze) -> movimenti. Trova l'intestazione dai nomi
    delle colonne e mappa data / importo / descrizione. Formato-agnostico."""
    header_idx = None
    cols = None
    for i, row in enumerate(rows):
        detected = _detect_columns(row)
        if detected:
            header_idx, cols = i, detected
            break
    if cols is None:
        return []

    movimenti: list[dict] = []
    for row in rows[header_idx + 1 :]:
        if not any(c not in (None, "") for c in row):
            continue  # riga vuota

        data = _coerce_date(_cell(row, cols["date"]))
        if data is None:
            continue

        importo_val = None
        if cols["amount"] is not None:
            importo_val = _coerce_amount(_cell(row, cols["amount"]))
        if importo_val is None:
            entrata = _coerce_amount(_cell(row, cols["entrate"]))
            uscita = _coerce_amount(_cell(row, cols["uscite"]))
            if entrata:
                importo_val = abs(entrata)
            elif uscita:
                importo_val = -abs(uscita)
        if importo_val is None:
            continue

        importo = abs(importo_val)
        if importo == 0:
            continue
        if (data_da and data < data_da) or (data_a and data > data_a):
            continue

        descr_val = _cell(row, cols["descr"])
        descrizione = re.sub(r"\s+", " ", str(descr_val or "")).strip()

        movimenti.append(
            {
                "provider": provider,
                "external_id": None,
                "tipo": "USCITA" if importo_val < 0 else "ENTRATA",
                "data": data,
                "importo": importo,
                "descrizione": descrizione or None,
            }
        )

    return movimenti


def _read_xlsx_rows(file_bytes: bytes) -> list:
    import openpyxl

    wb = openpyxl.load_workbook(
        io.BytesIO(file_bytes), read_only=True, data_only=True
    )
    try:
        ws = wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _read_csv_rows(file_bytes: bytes) -> list:
    import csv

    text = file_bytes.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    # Le banche italiane usano spesso ';' (la ',' è il separatore decimale).
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [list(r) for r in reader]


def parse_bank_statement_spreadsheet(
    file_bytes: bytes,
    filename: str,
    data_da: Optional[date] = None,
    data_a: Optional[date] = None,
) -> list[dict]:
    """Excel (.xlsx) o CSV (bytes) -> lista di candidati proposta."""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        rows = _read_csv_rows(file_bytes)
        provider = "CSV"
    else:
        rows = _read_xlsx_rows(file_bytes)
        provider = "EXCEL"
    return parse_statement_rows(
        rows, provider=provider, data_da=data_da, data_a=data_a
    )


def apply_filters_and_sort(query: Query, model, filters):
    # Soft-delete: le entità con `deleted_at` (Conto, Transazione) valorizzato sono
    # "cancellate" e non devono mai comparire nelle liste. Le escludiamo qui, in un
    # unico punto, così ogni endpoint che passa per questo helper è coperto
    # (conti, transazioni recenti/paginated).
    if hasattr(model, "deleted_at"):
        query = query.filter(model.deleted_at.is_(None))

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
