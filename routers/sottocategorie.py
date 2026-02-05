from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Categoria, Sottocategoria
from schemas import SottocategoriaCreate, SottocategoriaOut, SottocategoriaUpdate

router = APIRouter(tags=["Sottocategorie"])

# --- ENDPOINT SOTTOCATEGORIE ---


@router.post(
    "/categorie/{categoria_id}/sottocategorie", response_model=list[SottocategoriaOut]
)
def add_sottocategorie(
    categoria_id: int,
    sub_data_list: list[SottocategoriaCreate],
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Verify parent category ownership
    db_cat = (
        db.query(Categoria)
        .filter(Categoria.id == categoria_id, Categoria.user_id == current_user_id)
        .first()
    )

    if not db_cat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent category not found or unauthorized",
        )

    try:
        # 2. Create and add each subcategory from the list
        new_subcategories = []
        for sub_data in sub_data_list:
            # Optional: Check if a subcategory with the same name already exists in this category
            new_sub = Sottocategoria(
                nome=sub_data.nome, categoria_id=categoria_id, user_id=current_user_id
            )
            db.add(new_sub)
            new_subcategories.append(new_sub)

        # 3. Commit all subcategories at once
        db.commit()

        for sub in new_subcategories:
            db.refresh(sub)

        return new_subcategories
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating subcategories",
        )


@router.put("/sottocategorie/{sottocategoria_id}", response_model=SottocategoriaOut)
def update_sottocategoria(
    sottocategoria_id: int,
    sub_data: SottocategoriaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_sub = (
        db.query(Sottocategoria)
        .filter(
            Sottocategoria.id == sottocategoria_id,
            Sottocategoria.user_id == current_user_id,
        )
        .first()
    )

    if not db_sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subcategory not found or unauthorized",
        )

    try:
        db_sub.nome = sub_data.nome
        db.commit()
        db.refresh(db_sub)
        return db_sub
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update the subcategory",
        )


@router.delete(
    "/sottocategorie/{sottocategoria_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_sottocategoria(
    sottocategoria_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_sub = (
        db.query(Sottocategoria)
        .filter(
            Sottocategoria.id == sottocategoria_id,
            Sottocategoria.user_id == current_user_id,
        )
        .first()
    )

    if not db_sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subcategory not found"
        )

    try:
        db.delete(db_sub)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the subcategory. It may be linked to existing transactions",
        )
