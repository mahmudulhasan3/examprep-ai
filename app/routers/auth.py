from fastapi import APIRouter, Depends, HTTPException
from app.schemas.user import (
    UserRegisterRequest,
    UserRegisterResponse,
    UserLoginRequest,
    TokenResponse,
)
from app.core.security import hash_password, verify_password, create_token_access
from app.db.database import get_db
from app.db.models import User
from sqlalchemy.orm import Session

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserRegisterResponse)
def register(user_data: UserRegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=409, detail="User already exists")
    hashed_pw = hash_password(user_data.password)
    new_user = User(email=user_data.email, hashed_password=hashed_pw)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.post("/login", response_model=TokenResponse)
def login(user_data: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail= "No account found with this email. Please register first.")
    if not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    access_token = create_token_access({"user_id": user.id})
    return {"access_token": access_token, "token_type": "bearer"}
