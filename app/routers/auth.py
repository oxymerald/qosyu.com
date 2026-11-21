from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, get_password_hash, verify_password
from config import settings
from database import get_db
from dependencies import get_current_user
from models import User
from schemas import LoginIn, PasswordChange, Token, UserCreate, UserOut
from security import rate_limit

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


async def production_login_limit(request: Request):
    # Local demo keeps the previously requested unrestricted sign-in.
    if settings.is_production:
        await rate_limit("login", limit=20, window_seconds=300)(request)


@router.post("/login", response_model=Token, dependencies=[Depends(production_login_limit)])
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    # Единое сообщение об ошибке: не раскрываем, существует ли email
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")
    token, expires_in = create_access_token(user.id, user.role.value, user.token_version or 0)
    return Token(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post(
    "/telegram-link-code",
    dependencies=[Depends(rate_limit("tg-link-code", limit=10, window_seconds=600))],
)
async def telegram_link_code(current_user: User = Depends(get_current_user)):
    """Одноразовый код для привязки Telegram: отправьте боту /link <код>."""
    from services.link_codes import CODE_TTL_SECONDS, issue

    code = await issue(current_user.id)
    return {"code": code, "expires_in": CODE_TTL_SECONDS}


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=403, detail="Текущий пароль неверен")
    user_id = current_user.id
    user_role = current_user.role.value
    new_version = (current_user.token_version or 0) + 1
    current_user.hashed_password = get_password_hash(data.new_password)
    current_user.token_version = new_version
    db.add(current_user)
    await db.commit()
    token, expires_in = create_access_token(user_id, user_role, new_version)
    return {
        "message": "Пароль изменён",
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }
