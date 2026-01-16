from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas, auth

router = APIRouter(
    prefix="/tags",      # Tutti gli endpoint in questo file inizieranno con /tags
    tags=["Tag"]        # Raggruppa questi endpoint nella documentazione Swagger
)

# --- ENDPOINT TAG ---

@router.post("", response_model=schemas.TagOut)
def create_tag(tag: schemas.TagCreate, db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    new_tag = models.Tag(nome=tag.nome, user_id=current_user_id)
    db.add(new_tag)
    db.commit()
    db.refresh(new_tag)
    return new_tag

@router.get("", response_model=list[schemas.TagOut])
def get_tags(db: Session = Depends(get_db), current_user_id: int = Depends(auth.get_current_user_id)):
    return db.query(models.Tag).filter(models.Tag.user_id == current_user_id).all()