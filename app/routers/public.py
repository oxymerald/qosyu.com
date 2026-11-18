"""Public pilot intake. No registration and no external message forwarding."""
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import PilotApplication
from security import rate_limit

router = APIRouter(prefix="/public", tags=["public"])


class PilotIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company_name: str = Field(min_length=2, max_length=120)
    contact: str = Field(min_length=3, max_length=160)
    comment: str = Field(default="", max_length=2000)
    language: Literal["ru", "en", "kk"] = "ru"

    @field_validator("company_name", "contact")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("Control characters are not allowed")
        return value


@router.post(
    "/pilot",
    status_code=201,
    dependencies=[Depends(rate_limit("pilot", limit=5, window_seconds=3600))],
)
async def submit_pilot(data: PilotIn, db: AsyncSession = Depends(get_db)):
    application = PilotApplication(**data.model_dump())
    db.add(application)
    await db.commit()
    # Acknowledge only after the database has accepted the application.
    return {"accepted": True}
