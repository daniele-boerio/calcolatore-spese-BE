from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func, case
from typing import Optional
from database import get_db
from auth import get_current_user_id
from models import Transazione, Categoria, Sottocategoria

router = APIRouter(prefix="/statistics", tags=["Statistics"])


@router.get("/yearDetails")
def get_year_details_statistics(
    year: int = Query(..., description="L'anno di riferimento"),
    categoria_id: Optional[int] = Query(None, description="Filtra per categoria padre"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # 1. Definiamo quale colonna usare come "Etichetta" (Categoria o Sottocategoria)
    if categoria_id:
        label_col = Sottocategoria.nome
        join_model = Sottocategoria
        join_condition = Transazione.sottocategoria_id == Sottocategoria.id
    else:
        label_col = Categoria.nome
        join_model = Categoria
        join_condition = Transazione.categoria_id == Categoria.id

    # 2. Definiamo la logica di calcolo dell'importo
    # Usiamo importo_netto (con fallback su importo se per caso è NULL)
    # Le uscite diventano negative, le entrate positive.
    amount_expr = func.coalesce(Transazione.importo_netto, Transazione.importo)

    calculated_amount = case(
        (Transazione.tipo == "USCITA", -amount_expr),
        (Transazione.tipo == "ENTRATA", amount_expr),
        else_=0,  # I RIMBORSI vengono scartati perché il loro valore è già sottratto dal padre
    )

    # 3. Costruiamo la query principale
    query = (
        db.query(
            extract("month", Transazione.data).label("month"),
            label_col.label("label"),
            func.sum(calculated_amount).label("total"),
        )
        # Usiamo outerjoin così se una transazione non ha categoria non scompare dai conti
        .outerjoin(join_model, join_condition)
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            Transazione.tipo
            != "RIMBORSO",  # Escludiamo i figli per non sdoppiare il calcolo
        )
    )

    # 4. Applichiamo il filtro della categoria se l'utente l'ha selezionata
    if categoria_id:
        query = query.filter(Transazione.categoria_id == categoria_id)

    # 5. Raggruppiamo per mese ed etichetta
    results = query.group_by("month", "label").all()

    # --- POST-ELABORAZIONE IN PYTHON ---
    # Creiamo un dizionario di base con tutti i 12 mesi a zero
    # Questo garantisce che il frontend riceva sempre la struttura completa
    monthly_data = {m: {"month": m} for m in range(1, 13)}

    for row in results:
        # Se il database restituisce float o Decimal, lo convertiamo in modo sicuro
        month_int = int(row.month)
        # Se l'etichetta è NULL (es. transazione senza categoria), le diamo un nome generico
        label = row.label if row.label else "Uncategorized"
        total = float(row.total or 0)

        # Popoliamo il dizionario dinamico
        monthly_data[month_int][label] = total

    # Restituiamo solo i valori (una lista di dizionari)
    return list(monthly_data.values())


@router.get("/monthDetails")
def get_month_details_statistics(
    year: int = Query(..., description="L'anno di riferimento"),
    month: int = Query(..., description="Il mese di riferimento (1-12)"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # 1. Definiamo la logica di calcolo dell'importo (identica a yearTable)
    amount_expr = func.coalesce(Transazione.importo_netto, Transazione.importo)

    calculated_amount = case(
        (Transazione.tipo == "USCITA", -amount_expr),
        (Transazione.tipo == "ENTRATA", amount_expr),
        else_=0,  # Escludiamo i RIMBORSI dal calcolo diretto
    )

    # 2. Costruiamo la query principale aggregando per Categoria E Sottocategoria
    query = (
        db.query(
            Categoria.nome.label("categoria_nome"),
            Sottocategoria.nome.label("sottocategoria_nome"),
            func.sum(calculated_amount).label("total"),
        )
        .outerjoin(Categoria, Transazione.categoria_id == Categoria.id)
        .outerjoin(Sottocategoria, Transazione.sottocategoria_id == Sottocategoria.id)
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            extract("month", Transazione.data) == month,
            Transazione.tipo != "RIMBORSO",
        )
        .group_by(Categoria.nome, Sottocategoria.nome)
    )

    results = query.all()

    # --- POST-ELABORAZIONE IN PYTHON ---
    details = []

    for row in results:
        # Gestiamo i casi in cui la transazione non ha categoria o sottocategoria
        cat_name = row.categoria_nome if row.categoria_nome else "Uncategorized"
        sub_name = (
            row.sottocategoria_nome
            if row.sottocategoria_nome
            else "Nessuna sottocategoria"
        )
        total = float(row.total or 0)

        details.append(
            {"categoria": cat_name, "sottocategoria": sub_name, "totale": total}
        )

    # Ordiniamo i risultati prima per Categoria e poi per Sottocategoria alfabeticamente
    details_sorted = sorted(
        details, key=lambda x: (x["categoria"], x["sottocategoria"])
    )

    return details_sorted
