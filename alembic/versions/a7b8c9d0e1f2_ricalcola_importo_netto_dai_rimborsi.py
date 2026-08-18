"""ricalcola importo_netto dai rimborsi

Ripara le spese il cui `importo_netto` non corrisponde più a
lordo - somma dei rimborsi.

Come si erano rotte: la migration c3f81a9d2e07 ha fatto
`UPDATE transazioni SET importo_netto = importo WHERE importo_netto IS NULL`
sostenendo che "per una transazione senza rimborsi il netto coincide con il
lordo". Vero, ma quella UPDATE non escludeva i padri CHE AVEVANO rimborsi: se
una spesa era arrivata lì con il netto ancora NULL — perché i suoi rimborsi
erano stati registrati prima che esistesse la contabilità del netto — si è
ripresa il lordo, e quei rimborsi sono spariti dagli aggregati. La card della
categoria mostrava una spesa più alta del vero, mentre la lista continuava a
mostrare i rimborsi: i due numeri non tornavano.

Il ricalcolo somma TUTTI i rimborsi figli, senza filtrare `deleted_at`: è
esattamente ciò che fa `adjust_parent_netto` a runtime (la soft-delete di un
conto non storna il netto del padre, ed è reversibile con /conti/{id}/restore).
Filtrare qui i soft-eliminati avrebbe scritto un netto diverso da quello che il
codice mantiene, rompendo il restore.

Tocca solo le righe che sono davvero incoerenti: se il DB è sano non scrive
nulla.

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RICALCOLO = """
UPDATE transazioni AS p
SET importo_netto = p.importo - r.totale
FROM (
    SELECT parent_transaction_id AS pid, SUM(importo) AS totale
    FROM transazioni
    WHERE tipo = 'RIMBORSO'
      AND parent_transaction_id IS NOT NULL
    GROUP BY parent_transaction_id
) AS r
WHERE p.id = r.pid
  AND p.importo_netto IS DISTINCT FROM p.importo - r.totale
"""


def upgrade() -> None:
    """Rimette il netto in riga con i rimborsi realmente presenti."""
    op.execute(sa.text(RICALCOLO))


def downgrade() -> None:
    """Nessun downgrade: il valore precedente era quello sbagliato.

    Non esiste un modo di sapere quale netto errato aveva ogni riga prima del
    ricalcolo, e ripristinarlo significherebbe reintrodurre di proposito il
    disallineamento fra card e lista.
    """
    pass
