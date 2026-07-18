from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, get_password_hash, verify_password
from database import get_db
from dependencies import get_current_user
from models import User
from schemas import LoginIn, PasswordChange, Token, UserCreate, UserOut
from security import client_ip, rate_limit, rate_limiter

router = APIRouter()


@router.post(
    "/register",
    response_model=UserOut,
    status_code=201,
    dependencies=[Depends(rate_limit("register", limit=10, window_seconds=3600))],
)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == user.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Такой email уже зарегистрирован")
    db_user = User(
        email=user.email,
        hashed_password=get_password_hash(user.password),
        company_name=user.company_name,
        role=user.role,
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(rate_limit("login-ip", limit=20, window_seconds=900))],
)
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    # Отдельный, более строгий лимит на конкретную пару IP+email — от перебора пароля
    if not await rate_limiter.hit(f"login:{client_ip(request)}:{data.email}", 5, 900):
        raise HTTPException(
            status_code=429,
            detail="Слишком много попыток входа. Попробуйте через 15 минут.",
            headers={"Retry-After": "900"},
        )
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    # Единое сообщение об ошибке: не раскрываем, существует ли email
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    token, expires_in = create_access_token(user.id, user.role.value)
    return Token(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Текущий пароль неверен")
    current_user.hashed_password = get_password_hash(data.new_password)
    db.add(current_user)
    await db.commit()
    return {"message": "Пароль изменён"}
