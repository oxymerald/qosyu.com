from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import InvalidTokenError, decode_token
from database import get_db
from models import User, UserRole

security = HTTPBearer(auto_error=False)

_credentials_error = HTTPException(
    status_code=401,
    detail="Требуется авторизация",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise _credentials_error
    try:
        payload = decode_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (InvalidTokenError, ValueError):
        raise _credentials_error
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _credentials_error
    return user


def require_roles(*roles: UserRole):
    """Зависимость: пускает только пользователей с одной из указанных ролей."""

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user

    return dependency
