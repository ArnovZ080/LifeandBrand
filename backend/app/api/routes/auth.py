from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.db.database import get_db
from app.models.user import User, UserRole
from app.models.location import OrgUnit, OrgTier
from app.auth.security import verify_password, hash_password, create_access_token
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    org_unit_id: int
    org_unit_name: str

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: UserRole
    org_unit_id: int


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token(user.id)
    return Token(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        role=current_user.role.value,
        org_unit_id=current_user.org_unit_id,
        org_unit_name=current_user.org_unit.name,
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        name=payload.name,
        role=payload.role,
        org_unit_id=payload.org_unit_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value,
        org_unit_id=user.org_unit_id,
        org_unit_name=user.org_unit.name,
    )
