from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth

router = APIRouter(
    prefix="/categorie",      # Tutti gli endpoint in questo file inizieranno con /categorie
    tags=["Categorie"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT CATEGORIE ---

@router.post("", response_model=schemas.CategoriaOut)
def create_categoria(
    categoria: schemas.CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Grazie alla relazione 'sottocategorie' definita nel modello, 
    # SQLAlchemy gestisce la creazione nidificata se passiamo gli oggetti sottocategoria
    sub_models = [models.Sottocategoria(nome=s.nome) for s in (categoria.sottocategorie or [])]
    
    new_cat = models.Categoria(
        nome=categoria.nome, 
        user_id=current_user_id,
        sottocategorie=sub_models
    )

    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    return new_cat

@router.get("", response_model=list[schemas.CategoriaOut])
def get_categorie(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recupera le categorie e le loro sottocategorie associate
    return db.query(models.Categoria).filter(
        models.Categoria.user_id == current_user_id
    ).order_by(models.Categoria.nome).all()

@router.put("/{categoria_id}", response_model=schemas.CategoriaOut)
def update_categoria(
    categoria_id: int, 
    cat_data: schemas.CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Cerchiamo la categoria verificando che appartenga all'utente
    db_cat = db.query(models.Categoria).filter(
        models.Categoria.id == categoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_cat:
        raise HTTPException(
            status_code=404, 
            detail="Categoria non trovata o non disponi dei permessi necessari."
        )

    # Aggiorniamo solo il nome della categoria principale
    db_cat.nome = cat_data.nome

    db.commit()
    db.refresh(db_cat)
    return db_cat

@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(
    categoria_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    db_cat = db.query(models.Categoria).filter(
        models.Categoria.id == categoria_id,
        models.Categoria.user_id == current_user_id
    ).first()

    if not db_cat:
        raise HTTPException(status_code=404, detail="Categoria non esistente.")

    db.delete(db_cat)
    db.commit()
    return None