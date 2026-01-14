from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from routers.user import get_current_month_expenses
import models, schemas, auth

router = APIRouter(
    prefix="/budget",      # Tutti gli endpoint in questo file inizieranno con /budget
    tags=["Budget"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT BUDGET E SPESE ---

@router.put("/monthlyBudget")
def update_monthly_budget(
    budget_data: schemas.UserBudgetUpdate, # Assicurati di creare questo schema
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    user = db.query(models.User).filter(models.User.id == current_user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")

    # Aggiorniamo il budget nel database
    user.total_budget = budget_data.totalBudget
    db.commit()
    
    # Restituiamo i dati aggiornati (richiamando la logica di calcolo)
    return get_current_month_expenses(db, current_user_id)
