from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Categoria, Sottocategoria
from schemas import CategoriaCreate, CategoriaOut, CategoriaUpdate, CategoriaFilters
from services import apply_filters_and_sort
from sqlalchemy.orm import contains_eager

router = APIRouter(prefix="/categorie", tags=["Categorie"])

# --- ENDPOINT CATEGORIE ---


@router.post("", response_model=CategoriaOut)
def create_categoria(
    categoria: CategoriaCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    try:
        # Assign user_id explicitly to each subcategory during creation
        sottocategorie = [
            Sottocategoria(nome=s.nome, user_id=current_user_id)
            for s in (categoria.sottocategorie or [])
        ]

        nuova_categoria = Categoria(
            nome=categoria.nome, user_id=current_user_id, sottocategorie=sottocategorie
        )

        db.add(nuova_categoria)
        db.commit()
        db.refresh(nuova_categoria)
        return nuova_categoria
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the category and its subcategories",
        )


@router.get("", response_model=list[CategoriaOut])
def get_categorie(
    db: Session = Depends(get_db),
    filters: CategoriaFilters = Depends(),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Iniziamo con un JOIN esplicito tra Categoria e Sottocategoria
    # Usiamo outerjoin per non perdere le categorie che non hanno sottocategorie
    query = (
        db.query(Categoria)
        .outerjoin(Categoria.sottocategorie)
        .filter(Categoria.user_id == current_user_id)
    )

    # 2. Applichiamo i filtri principali (che ora funzionano su entrambi)
    if filters.solo_entrata:
        query = query.filter(Categoria.solo_entrata)
        query = query.filter(
            or_(Sottocategoria.id.is_(None), Sottocategoria.solo_entrata)
        )

    if filters.solo_uscita:
        query = query.filter(Categoria.solo_uscita)
        query = query.filter(
            or_(Sottocategoria.id.is_(None), Sottocategoria.solo_uscita)
        )

    if filters.solo_rimborso:
        query = query.filter(Categoria.solo_rimborso)
        query = query.filter(
            or_(Sottocategoria.id.is_(None), Sottocategoria.solo_rimborso)
        )

    # 3. Applichiamo la funzione di sorting/filtering generica
    query = apply_filters_and_sort(query, Categoria, filters=filters)

    # 4. FONDAMENTALE: Ordiniamo anche le sottocategorie (es. per nome o data)
    # Se non specifichi questo, apply_filters_and_sort ordina solo le categorie
    query = query.order_by(Categoria.nome, Sottocategoria.nome)

    # 5. Diciamo a SQLAlchemy di popolare la relazione .sottocategorie
    # usando i risultati di questa query filtrata e ordinata
    query = query.options(contains_eager(Categoria.sottocategorie))

    return query.all()


@router.put("/{categoria_id}", response_model=CategoriaOut)
def update_categoria(
    categoria_id: int,
    cat_data: CategoriaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    categoria = (
        db.query(Categoria)
        .filter(Categoria.id == categoria_id, Categoria.user_id == current_user_id)
        .first()
    )

    if not categoria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found or unauthorized",
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
            detail="Failed to update category name",
        )


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(
    categoria_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    categoria = (
        db.query(Categoria)
        .filter(Categoria.id == categoria_id, Categoria.user_id == current_user_id)
        .first()
    )

    if not categoria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
        )

    try:
        db.delete(categoria)
        db.commit()
        return None
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot delete category. It may be linked to existing transactions or subcategories",
        )
