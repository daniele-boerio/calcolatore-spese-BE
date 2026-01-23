from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Categoria, Sottocategoria
from schemas import SottocategoriaCreate, SottocategoriaOut, SottocategoriaUpdate

router = APIRouter(
    tags=["Sottocategorie"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT SOTTOCATEGORIE (OPERAZIONI SINGOLE) ---

@router.post("/categorie/{categoria_id}/sottocategorie", response_model=list[SottocategoriaOut])
def add_sottocategorie(
    categoria_id: int,
    sub_data_list: list[SottocategoriaCreate], # Accetta una lista
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # 1. Verifica proprietà della categoria padre
    db_cat = db.query(Categoria).filter(
        Categoria.id == categoria_id,
        Categoria.user_id == current_user_id
    ).first()

    if not db_cat:
        raise HTTPException(status_code=404, detail="Categoria padre non trovata o non autorizzata")

    # 2. Crea e aggiungi ogni sottocategoria della lista
    new_subcategories = []
    for sub_data in sub_data_list:
        new_sub = Sottocategoria(
            nome=sub_data.nome, 
            categoria_id=categoria_id
        )
        db.add(new_sub)
        new_subcategories.append(new_sub)

    # 3. Commit unico per tutte le nuove sottocategorie
    db.commit()
    
    # Rinfresca gli oggetti per ottenere gli ID generati
    for sub in new_subcategories:
        db.refresh(sub)
        
    return new_subcategories

@router.put("/sottocategorie/{sottocategoria_id}", response_model=SottocategoriaOut)
def update_sottocategoria(
    sottocategoria_id: int,
    sub_data: SottocategoriaUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Filtriamo direttamente sulla tabella Sottocategoria usando il suo user_id
    db_sub = db.query(Sottocategoria).filter(
        Sottocategoria.id == sottocategoria_id,
        Sottocategoria.user_id == current_user_id
    ).first()

    if not db_sub:
        raise HTTPException(
            status_code=404, 
            detail="Sottocategoria non trovata o non autorizzato"
        )

    db_sub.nome = sub_data.nome
    db.commit()
    db.refresh(db_sub)
    return db_sub

@router.delete("/sottocategorie/{sottocategoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sottocategoria(
    sottocategoria_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id)
):
    # Verifichiamo la proprietà
    db_sub = db.query(Sottocategoria).filter(
        Sottocategoria.id == sottocategoria_id,
        Sottocategoria.user_id == current_user_id
    ).first()

    if not db_sub:
        raise HTTPException(status_code=404, detail="Sottocategoria non trovata")

    db.delete(db_sub)
    db.commit()
    return None
