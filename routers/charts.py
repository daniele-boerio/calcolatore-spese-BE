from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from datetime import date
from typing import Optional, List
from pydantic import BaseModel
from database import get_db
from auth import get_current_user_id
from models import Transazione, Categoria

router = APIRouter(prefix="/charts", tags=["Charts"])

# --- SCHEMI DI RISPOSTA (Raw Data) ---


class MonthlyIncomeExpenseOut(BaseModel):
    label: str  # Formato "YYYY-MM" o "MM"
    entrate: float
    uscite: float


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


# --- ENDPOINT ---


@router.get("/income-expense", response_model=List[MonthlyIncomeExpenseOut])
def get_chart_income_expense(
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, multi_year = get_date_range(data_inizio, data_fine)

    results = (
        db.query(
            extract("year", Transazione.data).label("year"),
            extract("month", Transazione.data).label("month"),
            Transazione.tipo,
            func.sum(Transazione.importo_netto).label("total"),
        )
        .filter(
            Transazione.user_id == current_user_id,
            Transazione.data >= inizio,
            Transazione.data <= fine,
            Transazione.tipo != "RIMBORSO",
        )
        .group_by("year", "month", Transazione.tipo)
        .all()
    )

    labels = generate_month_labels(inizio, fine, multi_year)
    monthly_data = {
        label: {"label": label, "entrate": 0.0, "uscite": 0.0} for label in labels
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

    return list(monthly_data.values())


@router.get("/savings", response_model=List[MonthlySavingsOut])
def get_chart_savings(
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, multi_year = get_date_range(data_inizio, data_fine)

    results = (
        db.query(
            extract("year", Transazione.data).label("year"),
            extract("month", Transazione.data).label("month"),
            Transazione.tipo,
            func.sum(Transazione.importo_netto).label("total"),
        )
        .filter(
            Transazione.user_id == current_user_id,
            Transazione.data >= inizio,
            Transazione.data <= fine,
            Transazione.tipo != "RIMBORSO",
        )
        .group_by("year", "month", Transazione.tipo)
        .all()
    )

    labels = generate_month_labels(inizio, fine, multi_year)
    monthly_data = {
        label: {"label": label, "entrate": 0.0, "uscite": 0.0} for label in labels
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

    savings_list = []
    for label in labels:
        data = monthly_data[label]
        risparmio = data["entrate"] - data["uscite"]
        savings_list.append({"label": label, "risparmio": round(risparmio, 2)})

    return savings_list


@router.get("/expense-composition", response_model=List[ExpenseCompositionOut])
def get_chart_expense_composition(
    data_inizio: Optional[date] = Query(
        None, description="Data inizio (es: 2026-01-01)"
    ),
    data_fine: Optional[date] = Query(None, description="Data fine (es: 2026-12-31)"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, _ = get_date_range(data_inizio, data_fine)

    query = (
        db.query(
            Categoria.nome.label("categoria"),
            func.sum(Transazione.importo_netto).label("total"),
        )
        .outerjoin(Categoria, Transazione.categoria_id == Categoria.id)
        .filter(
            Transazione.user_id == current_user_id,
            Transazione.data >= inizio,
            Transazione.data <= fine,
            Transazione.tipo == "USCITA",
        )
    )

    results = query.group_by(Categoria.nome).all()

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
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    inizio, fine, multi_year = get_date_range(data_inizio, data_fine)

    results = (
        db.query(
            extract("year", Transazione.data).label("year"),
            extract("month", Transazione.data).label("month"),
            func.sum(Transazione.importo_netto).label("total"),
        )
        .filter(
            Transazione.user_id == current_user_id,
            Transazione.categoria_id == categoria_id,
            Transazione.data >= inizio,
            Transazione.data <= fine,
            Transazione.tipo == "USCITA",
        )
        .group_by("year", "month")
        .all()
    )

    labels = generate_month_labels(inizio, fine, multi_year)
    monthly_data = {label: {"label": label, "spesa": 0.0} for label in labels}

    for row in results:
        y = int(row.year)
        m = int(row.month)
        label_key = f"{y}-{m:02d}" if multi_year else f"{m}"

        if label_key in monthly_data:
            monthly_data[label_key]["spesa"] = round(float(row.total or 0), 2)

    return list(monthly_data.values())
