from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from typing import Optional, List
from pydantic import BaseModel
from database import get_db
from auth import get_current_user_id
from models import Transazione, Categoria

router = APIRouter(prefix="/charts", tags=["Charts"])

# --- SCHEMI DI RISPOSTA (Raw Data) ---


class MonthlyIncomeExpenseOut(BaseModel):
    mese: int
    entrate: float
    uscite: float


class MonthlySavingsOut(BaseModel):
    mese: int
    risparmio: float


class ExpenseCompositionOut(BaseModel):
    categoria: str
    totale: float
    color: Optional[str] = (
        None  # Utile se si vuole passare il colore associato alla categoria nel DB
    )


class CategoryTrendOut(BaseModel):
    mese: int
    spesa: float


# --- ENDPOINT ---


@router.get("/income-expense", response_model=List[MonthlyIncomeExpenseOut])
def get_chart_income_expense(
    year: int = Query(..., description="L'anno di riferimento"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # Raggruppa per mese e per tipo
    results = (
        db.query(
            extract("month", Transazione.data).label("month"),
            Transazione.tipo,
            func.sum(Transazione.importo_netto).label("total"),
        )
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            Transazione.tipo != "RIMBORSO",  # Escludiamo i rimborsi
        )
        .group_by("month", Transazione.tipo)
        .all()
    )

    # Inizializza i 12 mesi
    monthly_data = {m: {"mese": m, "entrate": 0.0, "uscite": 0.0} for m in range(1, 13)}

    for row in results:
        month_idx = int(row.month)
        if row.tipo == "ENTRATA":
            monthly_data[month_idx]["entrate"] = float(row.total or 0)
        elif row.tipo == "USCITA":
            monthly_data[month_idx]["uscite"] = float(row.total or 0)

    return list(monthly_data.values())


@router.get("/savings", response_model=List[MonthlySavingsOut])
def get_chart_savings(
    year: int = Query(..., description="L'anno di riferimento"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # Riutilizziamo la stessa query di prima
    results = (
        db.query(
            extract("month", Transazione.data).label("month"),
            Transazione.tipo,
            func.sum(Transazione.importo_netto).label("total"),
        )
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            Transazione.tipo != "RIMBORSO",
        )
        .group_by("month", Transazione.tipo)
        .all()
    )

    monthly_data = {m: {"mese": m, "entrate": 0.0, "uscite": 0.0} for m in range(1, 13)}

    for row in results:
        month_idx = int(row.month)
        if row.tipo == "ENTRATA":
            monthly_data[month_idx]["entrate"] = float(row.total or 0)
        elif row.tipo == "USCITA":
            monthly_data[month_idx]["uscite"] = float(row.total or 0)

    # Calcoliamo il risparmio netto mensile
    savings_list = []
    for m in range(1, 13):
        data = monthly_data[m]
        risparmio = data["entrate"] - data["uscite"]
        savings_list.append({"mese": m, "risparmio": round(risparmio, 2)})

    return savings_list


@router.get("/expense-composition", response_model=List[ExpenseCompositionOut])
def get_chart_expense_composition(
    year: int = Query(..., description="L'anno di riferimento"),
    month: Optional[int] = Query(None, description="Filtra per mese specifico (1-12)"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # Raggruppa le uscite per categoria madre
    query = (
        db.query(
            Categoria.nome.label("categoria"),
            # Se vuoi passare il colore potresti aggiungere Categoria.color (se esiste nel tuo modello, non l'ho visto ma lo metto opzionale in schema)
            func.sum(Transazione.importo_netto).label("total"),
        )
        .outerjoin(Categoria, Transazione.categoria_id == Categoria.id)
        .filter(
            Transazione.user_id == current_user_id,
            extract("year", Transazione.data) == year,
            Transazione.tipo == "USCITA",
        )
    )

    if month:
        query = query.filter(extract("month", Transazione.data) == month)

    results = query.group_by(Categoria.nome).all()

    composition = []
    for row in results:
        label = row.categoria or "Uncategorized"
        # Se nel tuo modello non c'è il colore sulla categoria, passerà None e verà ignorato
        composition.append(
            {"categoria": label, "totale": round(float(row.total or 0), 2)}
        )

    # Ordiniamo in ordine decrescente di spesa per un grafico a torta più carino
    composition.sort(key=lambda x: x["totale"], reverse=True)

    return composition


@router.get("/category-trend", response_model=List[CategoryTrendOut])
def get_chart_category_trend(
    year: int = Query(..., description="L'anno di riferimento"),
    categoria_id: int = Query(..., description="L'ID della categoria da analizzare"),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # Raggruppa per mese per una specifica categoria
    results = (
        db.query(
            extract("month", Transazione.data).label("month"),
            func.sum(Transazione.importo_netto).label("total"),
        )
        .filter(
            Transazione.user_id == current_user_id,
            Transazione.categoria_id == categoria_id,
            extract("year", Transazione.data) == year,
            Transazione.tipo == "USCITA",
        )
        .group_by("month")
        .all()
    )

    monthly_data = {m: {"mese": m, "spesa": 0.0} for m in range(1, 13)}

    for row in results:
        month_idx = int(row.month)
        monthly_data[month_idx]["spesa"] = round(float(row.total or 0), 2)

    return list(monthly_data.values())
