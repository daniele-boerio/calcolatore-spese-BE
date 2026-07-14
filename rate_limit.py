"""Limiter condiviso.

Vive in un modulo a sé (e non in `main.py`) perché i router devono importarlo per
decorare i propri endpoint, e `main.py` importa i router: metterlo lì creerebbe un
ciclo di import.

Il conteggio è per indirizzo IP e in memoria: dietro a un reverse proxy assicurarsi
che l'IP reale arrivi (header `X-Forwarded-For` + `--proxy-headers` su uvicorn),
altrimenti tutte le richieste risultano provenire dal proxy e condividono lo stesso
budget. Con più worker/repliche il contatore non è condiviso: per un rate limit
davvero globale serve uno storage esterno (`storage_uri="redis://..."`).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
