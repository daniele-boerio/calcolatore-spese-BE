from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Categoria, Sottocategoria
from schemas import SottocategoriaCreate, SottocategoriaOut, SottocategoriaUpdate
from sqlalchemy.orm import joinedload

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
    # 1. Verifica proprietà e recupera i permessi della categoria madre
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
        new_subcategories = []
        for sub_data in sub_data_list:
            # 2. Logica di Ereditarietà: la sub non può superare i permessi della madre
            # Se la madre è False, forziamo la sub a False
            final_solo_entrata = sub_data.solo_entrata if db_cat.solo_entrata else False
            final_solo_uscita = sub_data.solo_uscita if db_cat.solo_uscita else False

            new_sub = Sottocategoria(
                nome=sub_data.nome.strip(),
                categoria_id=categoria_id,
                user_id=current_user_id,
                solo_entrata=final_solo_entrata,
                solo_uscita=final_solo_uscita,
            )
            db.add(new_sub)
            new_subcategories.append(new_sub)

        # 3. Commit unico per tutte le sottocategorie
        db.commit()

        # Refresh per ottenere gli ID generati dal database
        for sub in new_subcategories:
            db.refresh(sub)

        return new_subcategories

    except Exception as e:
        db.rollback()
        # Loggare l'errore internamente aiuta il debug
        print(f"Errore creazione sottocategorie: {e}")
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
    # 1. Carichiamo esplicitamente la categoria padre con joinedload
    db_sub = (
        db.query(Sottocategoria)
        .options(joinedload(Sottocategoria.categoria))  # <--- FONDAMENTALE
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
        update_data = sub_data.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            # Il check ora funzionerà perché .categoria è già caricata
            if key == "solo_entrata" and value is True:
                if not db_sub.categoria.solo_entrata:
                    continue

            if key == "solo_uscita" and value is True:
                if not db_sub.categoria.solo_uscita:
                    continue

            setattr(db_sub, key, value)

        db.commit()
        db.refresh(db_sub)
        return db_sub
    except Exception as e:
        db.rollback()
        print(f"ERRORE REALE: {str(e)}")  # Controlla i log del terminale!
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update the subcategory: {str(e)}",
        )


@router.delete(
    "/sottocategorie/{sottocategoria_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_sottocategoria(
    sottocategoria_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # Cerchiamo la sottocategoria assicurandoci che appartenga all'utente
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
        db.delete(db_sub)
        db.commit()
        # In una DELETE con 204, il return None è implicito,
        # ma scriverlo non fa male.
        return None
    except Exception as e:
        db.rollback()
        # Loggare l'errore reale (es. IntegrityError) aiuta te nel debug,
        # mentre l'utente riceve il messaggio generico.
        print(f"Errore eliminazione sub {sottocategoria_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cannot delete subcategory. It's likely linked to existing transactions.",
        )
