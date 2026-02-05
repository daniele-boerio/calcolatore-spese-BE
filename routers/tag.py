from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
import auth
from models import Tag
from schemas import TagCreate, TagOut, TagUpdate

router = APIRouter(prefix="/tags", tags=["Tag"])

# --- ENDPOINT TAG ---


@router.post("", response_model=TagOut)
def create_tag(
    tag: TagCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    # Check if tag with the same name already exists for this user
    existing_tag = (
        db.query(Tag)
        .filter(Tag.nome == tag.nome, Tag.user_id == current_user_id)
        .first()
    )

    if existing_tag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A tag with this name already exists",
        )

    try:
        new_tag = Tag(nome=tag.nome, user_id=current_user_id)
        db.add(new_tag)
        db.commit()
        db.refresh(new_tag)
        return new_tag
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the tag",
        )


@router.get("", response_model=list[TagOut])
def get_tags(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    return db.query(Tag).filter(Tag.user_id == current_user_id).all()


@router.put("/{tag_id}", response_model=TagOut)
def update_tag(
    tag_id: int,
    tag_data: TagUpdate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_tag = (
        db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == current_user_id).first()
    )

    if not db_tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found or not authorized",
        )

    try:
        db_tag.nome = tag_data.nome
        db.commit()
        db.refresh(db_tag)
        return db_tag
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update the tag",
        )


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(auth.get_current_user_id),
):
    db_tag = (
        db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == current_user_id).first()
    )

    if not db_tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found or not authorized",
        )

    try:
        db.delete(db_tag)
        db.commit()
        return
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the tag. It might be in use by some transactions",
        )
