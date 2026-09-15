from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from datetime import date
from typing import Optional, List
from pydantic import BaseModel
from database import get_db
from auth import get_current_user_id
from models import Transazione, Categoria, Sottocategoria
from services import importo_effettivo

router = APIRouter(prefix="/charts", tags=["Charts"])

# --- SCHEMI DI RISPOSTA (Raw Data) ---


class MonthlyIncomeExpenseOut(BaseModel):
    label: str  # Formato "YYYY-MM" o "MM"
    entrate: float
    uscite: float
    accantonamento: float = 0.0


class MonthlySavingsOut(BaseModel):
    label: str  # Formato "YYYY-MM" o "MM"
    risparmio: float


class ExpenseCompositionOut(BaseModel):
    categoria: str
    totale: float
    color: Optional[str] = (
        None  # Utile se si vuole passare il colore associato alla categoria nel DB
    )


class CategoryTrendOut(BaseModel):
    label: str  # Formato "YYYY-MM" o "MM"
    spesa: float


# --- FUNZIONI DI SUPPORTO ---
def get_date_range(data_inizio: Optional[date], data_fine: Optional[date]):
    """Restituisce le date formattate e la flag che indica se superano l'anno"""
    oggi = date.today()
    inizio = data_inizio or date(oggi.year, 1, 1)
    fine = data_fine or date(oggi.year, 12, 31)
    # Se il range copre più di un anno, mostriamo "YYYY-MM" anziché solo "MM"
    multi_year = inizio.year != fine.year
    return inizio, fine, multi_year


def generate_month_labels(inizio: date, fine: date, multi_year: bool):
    """Genera la lista ordinata dei mesi/anni nel range"""
    labels = []
    current_year = inizio.year
    current_month = inizio.month

    while (current_year < fine.year) or (
        current_year == fine.year and current_month <= fine.month
    ):
        if multi_year:
            labels.append(f"{current_year}-{current_month:02d}")
        else:
            labels.append(f"{current_month}")

        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1
    return labels


def filtra_tassonomia(
    query,
    categoria_id: Optional[int],
    sottocategoria_id: Optional[List[int]],
    tag_id: Optional[int],
):
    """I filtri dell'Analisi, uguali per tutti e quattro i grafici.

    Prima ogni card guardava l'anno intero e basta: scegliere una categoria in
    cima alla schermata cambiava le viste Mese e Anno, e qui sotto niente.
    """
    if categoria_id:
        query = query.filter(Transazione.categoria_id == categoria_id)

    if sottocategoria_id:
        query = query.filter(Transazione.sottocategoria_id.in_(sottocategoria_id))

    if tag_id:
        query = query.filter(Transazione.tag_id == tag_id)

    return query


# --- ENDPOINT ---


@router.get("/income-expense", response_model=List[MonthlyIncomeExpenseOut])
def get_chart_income_expense(
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    categoria_id: Optional[int] = Query(None, description="Filtra per categoria padre"),
    sottocategoria_id: Optional[List[int]] = Query(
        None, description="Filtra per sottocategoria (ripetibile)"
    ),
    tag_id: Optional[int] = Query(None, description="Filtra per tag"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, multi_year = get_date_range(data_inizio, data_fine)

    query = db.query(
        extract("year", Transazione.data).label("year"),
        extract("month", Transazione.data).label("month"),
        Transazione.tipo,
        func.sum(importo_effettivo()).label("total"),
    ).filter(
        Transazione.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.data >= inizio,
        Transazione.data <= fine,
        Transazione.tipo != "RIMBORSO",
        Transazione.tipo != "RICARICA",
    )
    query = filtra_tassonomia(query, categoria_id, sottocategoria_id, tag_id)

    results = query.group_by("year", "month", Transazione.tipo).all()

    labels = generate_month_labels(inizio, fine, multi_year)
    monthly_data = {
        label: {"label": label, "entrate": 0.0, "uscite": 0.0, "accantonamento": 0.0}
        for label in labels
    }

    for row in results:
        y = int(row.year)
        m = int(row.month)
        label_key = f"{y}-{m:02d}" if multi_year else f"{m}"

        # Filtro extra per sicurezza nel caso i dati cadano fuori dai mesi esatti del range calcolato
        if label_key in monthly_data:
            if row.tipo == "ENTRATA":
                monthly_data[label_key]["entrate"] = float(row.total or 0)
            elif row.tipo == "USCITA":
                monthly_data[label_key]["uscite"] = float(row.total or 0)
            elif row.tipo == "ACCANTONAMENTO":
                monthly_data[label_key]["accantonamento"] = float(row.total or 0)

    return list(monthly_data.values())


@router.get("/savings", response_model=List[MonthlySavingsOut])
def get_chart_savings(
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    categoria_id: Optional[int] = Query(None, description="Filtra per categoria padre"),
    sottocategoria_id: Optional[List[int]] = Query(
        None, description="Filtra per sottocategoria (ripetibile)"
    ),
    tag_id: Optional[int] = Query(None, description="Filtra per tag"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, multi_year = get_date_range(data_inizio, data_fine)

    query = db.query(
        extract("year", Transazione.data).label("year"),
        extract("month", Transazione.data).label("month"),
        Transazione.tipo,
        func.sum(importo_effettivo()).label("total"),
    ).filter(
        Transazione.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.data >= inizio,
        Transazione.data <= fine,
        Transazione.tipo != "RIMBORSO",
        Transazione.tipo != "RICARICA",
    )
    query = filtra_tassonomia(query, categoria_id, sottocategoria_id, tag_id)

    results = query.group_by("year", "month", Transazione.tipo).all()

    labels = generate_month_labels(inizio, fine, multi_year)
    monthly_data = {
        label: {"label": label, "entrate": 0.0, "uscite": 0.0, "accantonamento": 0.0}
        for label in labels
    }

    for row in results:
        y = int(row.year)
        m = int(row.month)
        label_key = f"{y}-{m:02d}" if multi_year else f"{m}"

        if label_key in monthly_data:
            if row.tipo == "ENTRATA":
                monthly_data[label_key]["entrate"] = float(row.total or 0)
            elif row.tipo == "USCITA":
                monthly_data[label_key]["uscite"] = float(row.total or 0)
            elif row.tipo == "ACCANTONAMENTO":
                monthly_data[label_key]["accantonamento"] = float(row.total or 0)

    savings_list = []
    for label in labels:
        data = monthly_data[label]
        # Risparmio = entrate - uscite - accantonamenti
        risparmio = data["entrate"] - data["uscite"] - data["accantonamento"]
        savings_list.append({"label": label, "risparmio": round(risparmio, 2)})

    return savings_list


@router.get("/expense-composition", response_model=List[ExpenseCompositionOut])
def get_chart_expense_composition(
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    categoria_id: Optional[int] = Query(None, description="Filtra per categoria padre"),
    sottocategoria_id: Optional[List[int]] = Query(
        None, description="Filtra per sottocategoria (ripetibile)"
    ),
    tag_id: Optional[int] = Query(None, description="Filtra per tag"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, _ = get_date_range(data_inizio, data_fine)

    # Con una categoria scelta le fette sono le sue sottocategorie: una sola
    # fetta grande quanto tutta la ciambella non direbbe niente. È la stessa
    # regola di /statistics/yearDetails.
    etichetta = Sottocategoria.nome if categoria_id else Categoria.nome
    join_model = Sottocategoria if categoria_id else Categoria
    join_on = (
        Transazione.sottocategoria_id == Sottocategoria.id
        if categoria_id
        else Transazione.categoria_id == Categoria.id
    )

    query = (
        db.query(
            etichetta.label("categoria"),
            func.sum(importo_effettivo()).label("total"),
        )
        .outerjoin(join_model, join_on)
        .filter(
            Transazione.user_id == current_user_id,
            Transazione.deleted_at.is_(None),
            Transazione.data >= inizio,
            Transazione.data <= fine,
            Transazione.tipo == "USCITA",
        )
    )
    query = filtra_tassonomia(query, categoria_id, sottocategoria_id, tag_id)

    results = query.group_by(etichetta).all()

    composition = []
    for row in results:
        label = row.categoria or "Uncategorized"
        composition.append(
            {"categoria": label, "totale": round(float(row.total or 0), 2)}
        )

    # Ordiniamo in ordine decrescente di spesa per un grafico a torta più carino
    composition.sort(key=lambda x: x["totale"], reverse=True)

    return composition


@router.get("/category-trend", response_model=List[CategoryTrendOut])
def get_chart_category_trend(
    categoria_id: int = Query(..., description="L'ID della categoria da analizzare"),
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    sottocategoria_id: Optional[List[int]] = Query(
        None, description="Filtra per sottocategoria (ripetibile)"
    ),
    tag_id: Optional[int] = Query(None, description="Filtra per tag"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, multi_year = get_date_range(data_inizio, data_fine)

    query = db.query(
        extract("year", Transazione.data).label("year"),
        extract("month", Transazione.data).label("month"),
        Transazione.tipo,
        func.sum(importo_effettivo()).label("total"),
    ).filter(
        Transazione.user_id == current_user_id,
        Transazione.deleted_at.is_(None),
        Transazione.categoria_id == categoria_id,
        Transazione.data >= inizio,
        Transazione.data <= fine,
        Transazione.tipo != "RIMBORSO",
        Transazione.tipo != "RICARICA",
    )
    query = filtra_tassonomia(query, None, sottocategoria_id, tag_id)

    results = query.group_by("year", "month", Transazione.tipo).all()

    labels = generate_month_labels(inizio, fine, multi_year)
    monthly_data = {label: {"label": label, "spesa": 0.0} for label in labels}

    for row in results:
        y = int(row.year)
        m = int(row.month)
        label_key = f"{y}-{m:02d}" if multi_year else f"{m}"

        if label_key in monthly_data:
            importo = float(row.total or 0)
            if row.tipo == "USCITA":
                monthly_data[label_key]["spesa"] += round(importo, 2)
            elif row.tipo == "ENTRATA":
                # Le entrate aumentano il trend positivo (o compensano le uscite nel caso misto)
                monthly_data[label_key]["spesa"] -= round(importo, 2)

    return list(monthly_data.values())
