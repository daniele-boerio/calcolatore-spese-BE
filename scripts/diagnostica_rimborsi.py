"""Esegue diagnostica_rimborsi.sql sul database configurato in BE/.env.

Sola lettura. Si collega con la stessa configurazione dell'app (`database.py`),
così non serve né psql né copiare credenziali da nessuna parte:

    cd BE
    ./venv/Scripts/python.exe scripts/diagnostica_rimborsi.py

Le query stanno nel .sql accanto, separate da righe `-- @@ <titolo>`: unica
copia, leggibile anche da un client grafico.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

# Lo script sta in BE/scripts/, ma importa i moduli dell'app che vivono in BE/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from database import SQLALCHEMY_DATABASE_URL, engine  # noqa: E402

SQL_PATH = Path(__file__).with_suffix(".sql")


def blocchi_sql(testo):
    """Spezza il file sui marcatori `-- @@ <titolo>`, scartando l'intestazione."""
    blocchi = []
    titolo, righe = None, []
    for riga in testo.splitlines():
        if riga.startswith("-- @@"):
            if titolo:
                blocchi.append((titolo, "\n".join(righe)))
            titolo, righe = riga[len("-- @@") :].strip(), []
        elif titolo:
            righe.append(riga)
    if titolo:
        blocchi.append((titolo, "\n".join(righe)))
    return blocchi


def formatta(valore):
    if isinstance(valore, Decimal):
        return f"{valore:,.2f}".replace(",", " ")
    return "" if valore is None else str(valore)


def stampa_tabella(righe):
    colonne = list(righe[0]._mapping.keys())
    dati = [[formatta(r._mapping[c]) for c in colonne] for r in righe]
    larghezze = [
        max(len(colonne[i]), max(len(d[i]) for d in dati)) for i in range(len(colonne))
    ]
    print("   " + "  ".join(c.ljust(larghezze[i]) for i, c in enumerate(colonne)))
    print("   " + "  ".join("-" * larghezze[i] for i in range(len(colonne))))
    for d in dati:
        print("   " + "  ".join(d[i].ljust(larghezze[i]) for i in range(len(d))))


def main():
    # Mostriamo su quale DB stiamo girando, ma senza la password.
    destinazione = SQLALCHEMY_DATABASE_URL.split("@")[-1]
    print(f"Database: {destinazione}\n")

    esiti = {}
    with engine.connect() as conn:
        for titolo, query in blocchi_sql(SQL_PATH.read_text(encoding="utf-8")):
            righe = conn.execute(text(query)).fetchall()
            esiti[titolo] = len(righe)

            print(f"== {titolo} — {len(righe)} righe")
            if righe:
                stampa_tabella(righe)
            else:
                print("   (nessuna)")
            print()

    scarti = esiti.get("Scarto del netto (query decisiva)", 0)
    orfani = esiti.get("Rimborsi orfani", 0)
    sfasati = esiti.get("Rimborsi in un mese diverso dal padre", 0)

    print("== Verdetto")
    if scarti:
        print(f"   {scarti} spese hanno il netto corrotto: le card sbagliano di")
        print("   'scarto'. Serve una migration che ricalcoli importo_netto.")
    elif orfani or sfasati:
        print("   I netti sono coerenti: nessuna card sta sbagliando i conti.")
        if orfani:
            print(f"   {orfani} rimborsi senza padre: si vedono ma non contano da")
            print("   nessuna parte (hanno però mosso il saldo del conto).")
        if sfasati:
            print(f"   {sfasati} rimborsi scontano un mese diverso da quello in cui")
            print("   compaiono nella lista: è la differenza che stai vedendo.")
    else:
        print("   Tutto coerente: la causa è altrove, mandami di nuovo i numeri.")


if __name__ == "__main__":
    main()
