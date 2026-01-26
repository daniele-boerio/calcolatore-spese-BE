from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Categoria, Sottocategoria
from schemas import CategoriaCreate, CategoriaOut, CategoriaUpdate

router = APIRouter(
    prefix="/categorie",      # Tutti gli endpoint in questo file inizieranno con /categorie
    tags=["Categorie"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT CATEGORIE ---

@router.post("", response_model=CategoriaOut)
def create_categoria(
    categoria: CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Assegniamo l'user_id esplicitamente a ogni sottocategoria durante la creazione
    sottocategorie = [
        Sottocategoria(nome=s.nome, user_id=current_user_id) 
        for s in (categoria.sottocategorie or [])
    ]
    
    nuova_categoria = Categoria(
        nome=categoria.nome, 
        user_id=current_user_id,
        sottocategorie=sottocategorie
    )

    db.add(nuova_categoria)
    db.commit()
    db.refresh(nuova_categoria)
    return nuova_categoria

@router.get("", response_model=list[CategoriaOut])
def get_categorie(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Recupera le categorie e le loro sottocategorie associate
    return db.query(Categoria).filter(
        Categoria.user_id == current_user_id
    ).order_by(Categoria.id).all()

@router.put("/{categoria_id}", response_model=CategoriaOut)
def update_categoria(
    categoria_id: int, 
    cat_data: CategoriaUpdate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Cerchiamo la categoria verificando che appartenga all'utente
    categoria = db.query(Categoria).filter(
        Categoria.id == categoria_id,
        Categoria.user_id == current_user_id
    ).first()

    if not categoria:
        raise HTTPException(
            status_code=404, 
            detail="Categoria non trovata o non disponi dei permessi necessari."
        )
    categoria.nome = cat_data.nome

    db.commit()
    db.refresh(categoria)
    return categoria

@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(
    categoria_id: int, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    categoria = db.query(Categoria).filter(
        Categoria.id == categoria_id,
        Categoria.user_id == current_user_id
    ).first()

    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria non trovata.")

    db.delete(categoria)
    db.commit()
    return None