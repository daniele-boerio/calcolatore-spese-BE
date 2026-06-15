-- =====================================================================
-- Conversione delle vecchie ricariche automatiche (USCITA + RIMBORSO)
-- nel nuovo tipo unico RICARICA (giroconto, una sola riga).
--
-- IMPORTANTE
--  * Fai PRIMA il backup:  pg_dump ... > backup.sql
--  * NON tocca il saldo dei conti: il saldo riflette gia' il giro,
--    e queste operazioni (raw SQL) non lo modificano.
--  * Esegui dentro la transazione e verifica prima del COMMIT.
--
-- Abbinamento gambe: stessa coppia utente + importo + data, conti diversi.
-- =====================================================================

-- (DIAGNOSTICA) Possibili ambiguita': stesso utente/importo/data con piu'
-- di una USCITA "Ricarica automatica verso ...". Se restituisce righe,
-- rivedi manualmente prima di convertire.
SELECT user_id, importo, data, COUNT(*)
FROM transazioni
WHERE tipo = 'USCITA' AND descrizione LIKE 'Ricarica automatica verso %'
GROUP BY user_id, importo, data
HAVING COUNT(*) > 1;

-- (DIAGNOSTICA) Anteprima delle coppie che verranno unite
SELECT u.id AS uscita_id, u.conto_id AS sorgente, r.conto_id AS destinazione,
       u.importo, u.data, u.descrizione
FROM transazioni u
JOIN transazioni r
  ON r.tipo = 'RIMBORSO'
 AND r.descrizione LIKE 'Ricarica automatica da %'
 AND r.user_id = u.user_id
 AND r.importo = u.importo
 AND r.data = u.data
 AND r.conto_id <> u.conto_id
WHERE u.tipo = 'USCITA'
  AND u.descrizione LIKE 'Ricarica automatica verso %';

-- =====================================================================
-- CONVERSIONE
-- =====================================================================
BEGIN;

-- 1) La gamba USCITA diventa la RICARICA, con il conto destinazione
--    preso dalla gamba RIMBORSO corrispondente.
UPDATE transazioni u
SET tipo = 'RICARICA',
    conto_destinazione_id = r.conto_id,
    parent_transaction_id = NULL
FROM transazioni r
WHERE u.tipo = 'USCITA'
  AND u.descrizione LIKE 'Ricarica automatica verso %'
  AND r.tipo = 'RIMBORSO'
  AND r.descrizione LIKE 'Ricarica automatica da %'
  AND r.user_id = u.user_id
  AND r.importo = u.importo
  AND r.data = u.data
  AND r.conto_id <> u.conto_id;

-- 2) Le gambe RIMBORSO sono ora assorbite nella RICARICA: si eliminano.
DELETE FROM transazioni
WHERE tipo = 'RIMBORSO'
  AND descrizione LIKE 'Ricarica automatica da %';

-- (VERIFICA) non devono restare USCITA/RIMBORSO di ricarica automatica
SELECT tipo, COUNT(*)
FROM transazioni
WHERE descrizione LIKE 'Ricarica automatica%'
GROUP BY tipo;

-- Se tutto torna:
COMMIT;
-- altrimenti:
-- ROLLBACK;
