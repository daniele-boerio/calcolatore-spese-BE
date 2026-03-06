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
        # 1. Definiamo i permessi della categoria madre (presi dal payload)
        cat_solo_entrata = categoria.solo_entrata
        cat_solo_uscita = categoria.solo_uscita

        # 2. Creiamo gli oggetti Sottocategoria applicando i vincoli della madre
        sottocategorie = [
            Sottocategoria(
                nome=s.nome.strip(),
                user_id=current_user_id,
                # La sub eredita il permesso SOLO SE la madre lo permette
                solo_entrata=s.solo_entrata if cat_solo_entrata else False,
                solo_uscita=s.solo_uscita if cat_solo_uscita else False,
            )
            for s in (categoria.sottocategorie or [])
        ]

        # 3. Creiamo la categoria madre includendo la lista delle figlie
        nuova_categoria = Categoria(
            nome=categoria.nome.strip(),
            user_id=current_user_id,
            solo_entrata=cat_solo_entrata,
            solo_uscita=cat_solo_uscita,
            sottocategorie=sottocategorie,
        )

        db.add(nuova_categoria)
        db.commit()
        db.refresh(nuova_categoria)
        return nuova_categoria

    except Exception as e:
        db.rollback()
        # Log dell'errore per il debug
        print(f"Errore creazione categoria nidificata: {e}")
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
    # 1. Join e filtro utente iniziale
    # Usiamo distinct() per evitare duplicati causati dal join 1:N
    query = (
        db.query(Categoria)
        .outerjoin(Categoria.sottocategorie)
        .filter(Categoria.user_id == current_user_id)
    )

    # 2. Filtri condizionali (Entrata / Uscita)
    # Importante: usiamo == True per chiarezza con SQLAlchemy
    if filters.solo_entrata:
        query = query.filter(Categoria.solo_entrata)
        # Filtriamo le sottocategorie: mostriamo quelle 'solo_entrata'
        # MA includiamo la categoria anche se non ha sottocategorie (id is None)
        query = query.filter(
            or_(Sottocategoria.id.is_(None), Sottocategoria.solo_entrata)
        )

    if filters.solo_uscita:
        query = query.filter(Categoria.solo_uscita)
        query = query.filter(
            or_(Sottocategoria.id.is_(None), Sottocategoria.solo_uscita)
        )

    # 3. Sorting e filtri generici (es. ricerca per nome)
    query = apply_filters_and_sort(query, Categoria, filters=filters)

    # 4. Ordinamento gerarchico
    # Ordiniamo prima la categoria madre, poi le figlie internamente
    query = query.order_by(Categoria.nome.asc(), Sottocategoria.nome.asc())

    # 5. Eager Loading con vincoli
    # Questo assicura che il JSON finale contenga SOLO le sottocategorie
    # che sono passate attraverso i filtri del punto 2
    query = query.options(contains_eager(Categoria.sottocategorie)).distinct()

    return query.all()


@router.put("/{categoria_id}", response_model=CategoriaOut)
def update_categoria(
    categoria_id: int,
    cat_data: CategoriaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # 1. Recupero della categoria con le sue sottocategorie
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
        # 2. Aggiornamento campi principali (usando model_dump per flessibilità)
        update_data = cat_data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(categoria, key, value)

        # 3. LOGICA DI CASCATA: Se la madre diventa restrittiva, aggiorna le figlie
        # Se solo_entrata della categoria diventa False, tutte le sub devono diventare False
        if not categoria.solo_entrata:
            for sub in categoria.sottocategorie:
                sub.solo_entrata = False

        # Se solo_uscita della categoria diventa False, tutte le sub devono diventare False
        if not categoria.solo_uscita:
            for sub in categoria.sottocategorie:
                sub.solo_uscita = False

        db.commit()
        db.refresh(categoria)
        return categoria

    except Exception as e:
        db.rollback()
        print(f"Errore update categoria {categoria_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update category and sync subcategories",
        )


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_categoria(
    categoria_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # Recuperiamo la categoria verificando la proprietà
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
        # Se nel modello hai impostato il cascade, questo eliminerà anche le sottocategorie
        db.delete(categoria)
        db.commit()
        return None
    except Exception as e:
        db.rollback()
        # Log interno per capire se il problema è un vincolo di integrità (ForeignKey)
        print(f"Errore eliminazione categoria {categoria_id}: {e}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot delete category. Ensure it's not linked to any existing transactions. You should delete or reassign transactions first.",
        )
