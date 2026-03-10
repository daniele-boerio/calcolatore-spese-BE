from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func, case
from typing import Optional
from database import get_db
from auth import get_current_user_id
from models import Transazione, Categoria, Sottocategoria

router = APIRouter(prefix="/statistics", tags=["Statistics"])


# Helper per calcolare l'importo standard per le statistiche
def get_calculated_amount():
    amount_expr = func.coalesce(Transazione.importo_netto, Transazione.importo)
    return case(
        (Transazione.tipo == "USCITA", -amount_expr),
        (Transazione.tipo == "ENTRATA", amount_expr),
        else_=0,  # I RIMBORSI vengono scartati
    )


@router.get("/yearDetails")
def get_year_details_statistics(
    year: int = Query(..., description="L'anno di riferimento"),
    categoria_id: Optional[int] = Query(None, description="Filtra per categoria padre"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # 1. Configurazione dinamica per Categoria vs Sottocategoria
    join_model = Sottocategoria if categoria_id else Categoria
    label_col = Sottocategoria.nome if categoria_id else Categoria.nome
    join_condition = (
        Transazione.sottocategoria_id == Sottocategoria.id
        if categoria_id
        else Transazione.categoria_id == Categoria.id
    )

    # 2. Query ottimizzata
    query = (
        db.query(
            extract("month", Transazione.data).label("month"),
            label_col.label("label"),
            func.sum(get_calculated_amount()).label("total"),
        )
        .outerjoin(join_model, join_condition)
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            Transazione.tipo != "RIMBORSO",
        )
    )

    if categoria_id:
        query = query.filter(Transazione.categoria_id == categoria_id)

    results = query.group_by("month", "label").all()

    # 3. Costruzione dizionario mensile pre-riempito (comprensione del dizionario)
    monthly_data = {m: {"month": m} for m in range(1, 13)}

    # 4. Popolamento efficiente
    for row in results:
        month_idx = int(row.month)
        label = row.label or "Uncategorized"
        monthly_data[month_idx][label] = float(row.total or 0)

    return list(monthly_data.values())


@router.get("/monthDetails")
def get_month_details_statistics(
    year: int = Query(..., description="L'anno di riferimento"),
    month: int = Query(..., description="Il mese di riferimento (1-12)"),
    categoria_id: Optional[int] = Query(None, description="Filtra per categoria padre"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # 1. Costruzione query
    query = (
        db.query(
            Categoria.nome.label("categoria_nome"),
            Categoria.solo_entrata,
            Categoria.solo_uscita,
            Sottocategoria.nome.label("sottocategoria_nome"),
            func.sum(get_calculated_amount()).label("total"),
        )
        .outerjoin(Categoria, Transazione.categoria_id == Categoria.id)
        .outerjoin(Sottocategoria, Transazione.sottocategoria_id == Sottocategoria.id)
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            extract("month", Transazione.data) == month,
            Transazione.tipo != "RIMBORSO",
        )
    )

    if categoria_id:
        query = query.filter(Transazione.categoria_id == categoria_id)

    query = query.group_by(
        Categoria.nome,
        Categoria.solo_entrata,
        Categoria.solo_uscita,
        Sottocategoria.nome,
    )

    results = query.all()

    # 2. Raggruppamento dati con dict.setdefault()
    categorie_dict = {}

    for row in results:
        cat_name = row.categoria_nome or "Uncategorized"
        sub_name = row.sottocategoria_nome or "Nessuna sottocategoria"
        total_sub = float(row.total or 0)

        # Determina il tipo di categoria in modo più snello
        tipo_cat = "other"
        if cat_name != "Uncategorized":
            if row.solo_entrata and not row.solo_uscita:
                tipo_cat = "entrata"
            elif row.solo_uscita and not row.solo_entrata:
                tipo_cat = "uscita"

        # Usa setdefault per inizializzare il dizionario se non esiste
        cat_data = categorie_dict.setdefault(
            cat_name,
            {
                "categoria": cat_name,
                "totale": 0.0,
                "tipo": tipo_cat,
                "sottocategorie": [],
            },
        )

        cat_data["totale"] += total_sub
        cat_data["sottocategorie"].append(
            {"sottocategoria": sub_name, "totale": total_sub}
        )

    # 3. Formattazione finale: ordinamento e arrotondamento
    details_list = []
    # Ordiniamo prima le chiavi del dizionario
    for cat_name in sorted(categorie_dict.keys()):
        cat = categorie_dict[cat_name]
        cat["totale"] = round(cat["totale"], 2)
        # Ordina le sottocategorie
        cat["sottocategorie"].sort(key=lambda x: x["sottocategoria"])
        details_list.append(cat)

    return details_list
