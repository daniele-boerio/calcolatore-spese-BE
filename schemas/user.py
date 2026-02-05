from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional


class UserBase(BaseModel):
    email: EmailStr
    username: str


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    id: int
    creationDate: datetime
    lastUpdate: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    username: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserBudgetUpdate(BaseModel):
    totalBudget: Optional[float] = None


class UserResponse(BaseModel):
    username: str
    email: str

    class Config:
        from_attributes = True
