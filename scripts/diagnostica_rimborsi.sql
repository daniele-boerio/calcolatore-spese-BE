-- Diagnostica: perché la card di una categoria non torna con la somma delle
-- righe mostrate cliccandola.
--
-- Le card mostrano `-importo_netto` della spesa (i rimborsi sono già scontati
-- dentro il padre), mentre la lista mostra le righe grezze. I due numeri
-- divergono per una di queste tre ragioni. Esegui le query in ordine.
-- Sola lettura: nessuna scrive niente.


-- 1) SCARTO DEL NETTO  ← la query decisiva
-- Padri il cui `importo_netto` registrato non è più uguale a
-- lordo - somma dei rimborsi vivi. Se qui esce qualcosa, il dato è corrotto:
-- il valore in `scarto` è esattamente quanto la card sbaglia.
SELECT p.id,
       p.data,
       p.descrizione,
       p.importo                                          AS lordo,
       p.importo_netto                                    AS netto_registrato,
       p.importo - COALESCE(SUM(r.importo), 0)            AS netto_atteso,
       p.importo_netto - (p.importo - COALESCE(SUM(r.importo), 0)) AS scarto,
       COUNT(r.id)                                        AS n_rimborsi
FROM transazioni p
LEFT JOIN transazioni r
       ON r.parent_transaction_id = p.id
      AND r.tipo = 'RIMBORSO'
      AND r.deleted_at IS NULL
WHERE p.deleted_at IS NULL
  AND p.tipo <> 'RIMBORSO'
GROUP BY p.id, p.data, p.descrizione, p.importo, p.importo_netto
HAVING p.importo_netto IS DISTINCT FROM p.importo - COALESCE(SUM(r.importo), 0)
ORDER BY ABS(p.importo_netto - (p.importo - COALESCE(SUM(r.importo), 0))) DESC;


-- 2) RIMBORSI ORFANI
-- Un RIMBORSO senza padre non scala niente e non compare in nessun aggregato
-- (le statistiche filtrano via `tipo = 'RIMBORSO'`), ma ha comunque mosso il
-- saldo del conto ed è visibile nella lista. Soldi che si vedono ma non contano.
SELECT id, data, importo, descrizione, conto_id, categoria_id
FROM transazioni
WHERE tipo = 'RIMBORSO'
  AND parent_transaction_id IS NULL
  AND deleted_at IS NULL
ORDER BY data DESC;


-- 3) RIMBORSI IN UN MESE DIVERSO DAL PADRE
-- Qui i conti sono giusti ma ingannano: il rimborso sconta il mese del PADRE,
-- mentre nella lista compare nel mese della PROPRIA data. Un rimborso di marzo
-- su una spesa di febbraio si vede in marzo ma alleggerisce febbraio.
SELECT r.id           AS rimborso_id,
       r.data         AS data_rimborso,
       r.importo,
       p.id           AS padre_id,
       p.data         AS data_padre,
       p.descrizione  AS padre_descrizione
FROM transazioni r
JOIN transazioni p ON p.id = r.parent_transaction_id
WHERE r.tipo = 'RIMBORSO'
  AND r.deleted_at IS NULL
  AND p.deleted_at IS NULL
  AND date_trunc('month', p.data) IS DISTINCT FROM date_trunc('month', r.data)
ORDER BY r.data DESC;
