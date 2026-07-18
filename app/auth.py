import re
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidTokenError(Exception):
    """Токен отсутствует, повреждён или просрочен."""


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> str | None:
    """Возвращает текст ошибки или None, если пароль допустим."""
    if len(password) < 8:
        return "Пароль должен быть не короче 8 символов"
    if len(password.encode("utf-8")) > 72:
        return "Пароль слишком длинный (максимум 72 байта)"
    if not re.search(r"[A-Za-zА-Яа-я]", password):
        return "Пароль должен содержать хотя бы одну букву"
    if not re.search(r"\d", password):
        return "Пароль должен содержать хотя бы одну цифру"
    return None


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    """Возвращает (токен, срок жизни в секундах)."""
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + expires,
        "jti": secrets.token_urlsafe(8),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(expires.total_seconds())


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise InvalidTokenError("Неверный тип токена")
    return payload
