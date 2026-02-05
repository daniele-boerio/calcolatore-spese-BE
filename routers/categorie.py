from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Categoria, Sottocategoria
from schemas import CategoriaCreate, CategoriaOut, CategoriaUpdate

router = APIRouter(
    prefix="/categorie",
    tags=["Categorie"]
)

# --- ENDPOINT CATEGORIE ---

@router.post("", response_model=CategoriaOut)
def create_categoria(
    categoria: CategoriaCreate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    try:
        # Assign user_id explicitly to each subcategory during creation
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
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the category and its subcategories"
        )

@router.get("", response_model=list[CategoriaOut])
def get_categorie(
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Fetch categories and their associated subcategories
    return db.query(Categoria).filter(
        Categoria.user_id == current_user_id
    ).all()

@router.put("/{categoria_id}", response_model=CategoriaOut)
def update_categoria(
    categoria_id: int, 
    cat_data: CategoriaUpdate, 
    db: Session = Depends(get_db), 
    current_user_id: int = Depends(auth.get_current_user_id)
):
    categoria = db.query(Categoria).filter(
        Categoria.id == categoria_id,
        Categoria.user_id == current_user_id
    ).first()

    if not categoria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Category not found or unauthorized"
        )
    
    try:
        categoria.nome = cat_data.nome
        db.commit()
        db.refresh(categoria)
        return categoria
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update category name"
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Category not found"
        )

    try:
        db.delete(categoria)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot delete category. It may be linked to existing transactions or subcategories"
        )