"""Gemini with read-only map tools; optional legacy Anthropic text assistant.

Without credentials the application works and operational insights use rules.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from dependencies import get_current_user, require_roles
from models import (
    CollectionZone,
    RequestStatus,
    User,
    UserRole,
    WasteRequest,
    ZoneStatus,
)
from security import rate_limit
from services.esg import calculate_co2_saved, collected_weights_query
from services import ai_tools, gemini

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

logger = logging.getLogger("qosyu.ai")

router = APIRouter(prefix="/ai", tags=["ai"])

_client = None


def _get_client():
    global _client
    if _client is None and anthropic is not None and settings.ANTHROPIC_API_KEY:
        _client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _ai_available() -> bool:
    if settings.AI_PROVIDER == "gemini":
        return bool(settings.GEMINI_API_KEY.strip())
    return settings.AI_PROVIDER == "anthropic" and anthropic is not None and bool(settings.ANTHROPIC_API_KEY)


SYSTEM_PROMPT = """Ты — ассистент QOSYU, цифровой платформы первой мили экологической логистики в Казахстане.

Платформа принимает заявки на сбор вторсырья и помогает переработчику работать с зонами. ESG-отчёт показывает массу переданного сырья и модельный эквивалент CO₂ по массе картона.

Платные тарифы и гарантированные сроки вывоза пока не предлагаются: стоимость, время и условия стороны согласуют напрямую.

Правила:
- Отвечай на языке пользователя (русский, казахский или английский).
- Кратко и по делу: 1-4 предложения, без воды.
- Помогай только по темам платформы: заявки, вывоз, переработка, ESG, маршруты, сортировка вторсырья.
- Давай практичные советы по подготовке вторсырья (чистый сухой картон, сплющенные коробки, ополоснутый пластик).
- Если вопрос не по теме — вежливо верни разговор к переработке.
- Не выдумывай данные, тарифы, цены или показатели, которых нет в контексте пользователя."""


class AssistantMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4000)


class MapStart(BaseModel):
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class AssistantIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[AssistantMessage] = Field(default_factory=list, max_length=10)
    map_start: MapStart | None = None
    selected_zone_id: int | None = Field(default=None, gt=0)


class MapSelection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


@router.post("/map/{kind}")
async def map_selection(
    kind: Literal["requests", "zones"],
    data: MapSelection,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ai_tools.map_items(kind, data.ids, db, current_user)


@router.get("/status")
async def ai_status():
    model = settings.GEMINI_MODEL if settings.AI_PROVIDER == "gemini" else settings.AI_MODEL
    return {"available": _ai_available(), "provider": settings.AI_PROVIDER,
            "model": model if _ai_available() else None,
            "map_tools": settings.AI_PROVIDER == "gemini" and _ai_available()}


async def _user_context(db: AsyncSession, user: User) -> str:
    """Персональный контекст пользователя для ассистента."""
    lines = [
        "Роль пользователя: "
        f"{'бизнес (сдаёт вторсырьё)' if user.role == UserRole.SME else 'переработчик' if user.role == UserRole.RECYCLER else 'администратор'}."
    ]
    if user.role == UserRole.SME:
        reqs = (
            await db.execute(
                select(WasteRequest)
                .where(WasteRequest.sme_id == user.id)
                .order_by(WasteRequest.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        if reqs:
            lines.append("Последние заявки: " + "; ".join(
                f"#{r.id} {r.waste_type.value} {r.weight_kg}кг ({r.status.value})" for r in reqs
            ))
        total, cardboard_kg = (await db.execute(collected_weights_query().where(
            WasteRequest.sme_id == user.id,
            WasteRequest.status.in_([RequestStatus.COLLECTED, RequestStatus.VERIFIED]),
        ))).one()
        lines.append(
            f"Всего передано: {round(total, 1)} кг. Модельный эквивалент для картона: "
            f"{calculate_co2_saved(cardboard_kg)} кг CO₂-экв."
        )
    elif user.role == UserRole.RECYCLER:
        open_zones = (
            await db.execute(
                select(func.count(CollectionZone.id), func.coalesce(func.sum(CollectionZone.total_weight_kg), 0.0))
                .where(CollectionZone.status == ZoneStatus.OPEN, CollectionZone.recycler_id.is_(None))
            )
        ).one()
        my_zones = (
            await db.execute(
                select(func.count(CollectionZone.id)).where(
                    CollectionZone.recycler_id == user.id,
                    CollectionZone.status.in_([ZoneStatus.ASSIGNED, ZoneStatus.IN_PROGRESS]),
                )
            )
        ).scalar()
        lines.append(
            f"Открытых зон сбора: {open_zones[0]} (суммарно {round(float(open_zones[1]), 1)} кг). "
            f"Зон в работе у пользователя: {my_zones}."
        )
    return "\n".join(lines)


@router.post(
    "/assistant",
    dependencies=[Depends(rate_limit("ai-assistant", limit=30, window_seconds=3600))],
)
async def assistant(
    data: AssistantIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if settings.AI_PROVIDER == "gemini":
        return await gemini.assistant(data, db, current_user)
    if not _ai_available():
        raise HTTPException(
            status_code=503,
            detail="AI-ассистент не настроен: задайте ANTHROPIC_API_KEY",
        )
    client = _get_client()
    context = await _user_context(db, current_user)
    messages = [{"role": m.role, "content": gemini.redact_private_text(m.content)} for m in data.history]
    messages.append({"role": "user", "content": gemini.redact_private_text(data.message)})
    try:
        response = await client.messages.create(
            model=settings.AI_MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": f"Контекст пользователя:\n{context}"},
            ],
            messages=messages,
        )
    except anthropic.AuthenticationError:
        logger.error("Неверный ANTHROPIC_API_KEY")
        raise HTTPException(status_code=503, detail="AI-ассистент настроен неверно")
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=429, detail="AI-ассистент перегружен, попробуйте через минуту"
        )
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error %s", exc.status_code)
        raise HTTPException(status_code=502, detail="AI-ассистент временно недоступен")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Нет связи с AI-сервисом")

    if response.stop_reason == "refusal":
        return {"reply": "Я не могу помочь с этим вопросом. Спросите меня о переработке, заявках или ESG-отчётности."}
    reply = next((b.text for b in response.content if b.type == "text"), "")
    return {"reply": reply}


@router.get(
    "/insights",
    dependencies=[Depends(rate_limit("ai-insights", limit=20, window_seconds=3600))],
)
async def insights(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles(UserRole.RECYCLER, UserRole.ADMIN)),
):
    """Операционная аналитика: правила всегда, Claude-рекомендации при наличии ключа."""
    pending = (
        await db.execute(
            select(
                func.count(WasteRequest.id),
                func.coalesce(func.sum(WasteRequest.weight_kg), 0.0),
            ).where(WasteRequest.status == RequestStatus.PENDING)
        )
    ).one()
    pending_count, pending_weight = pending[0], float(pending[1])

    top_type_row = (
        await db.execute(
            select(
                WasteRequest.waste_type,
                func.coalesce(func.sum(WasteRequest.weight_kg), 0.0),
            )
            .group_by(WasteRequest.waste_type)
            .order_by(func.sum(WasteRequest.weight_kg).desc())
            .limit(1)
        )
    ).first()
    top_type = top_type_row[0].value if top_type_row else None
    open_zones = (
        await db.execute(
            select(func.count(CollectionZone.id)).where(
                CollectionZone.status == ZoneStatus.OPEN
            )
        )
    ).scalar() or 0

    stats = {
        "pending_requests": pending_count,
        "pending_weight_kg": round(pending_weight, 1),
        "open_zones": open_zones,
        "top_waste_type": top_type,
    }

    # Rule-based рекомендации — работают всегда
    recommendations = []
    if pending_count >= 2 and open_zones == 0:
        recommendations.append(
            f"Накопилось {pending_count} заявок ({round(pending_weight)} кг) — запустите "
            "кластеризацию, чтобы сформировать зоны сбора."
        )
    if open_zones > 0:
        recommendations.append(
            f"Открыто {open_zones} зон — возьмите ближайшую в работу, маршрут построится автоматически."
        )
    if top_type:
        recommendations.append(
            f"Больше всего сырья по типу «{top_type}» — имеет смысл договориться с профильным переработчиком."
        )
    if not recommendations:
        recommendations.append("Пока недостаточно данных — создайте несколько заявок для аналитики.")

    source = "rules"
    if settings.AI_PROVIDER == "anthropic" and _ai_available():
        try:
            client = _get_client()
            response = await client.messages.create(
                model=settings.AI_MODEL,
                max_tokens=600,
                system="Ты — операционный аналитик платформы сбора вторсырья QOSYU. "
                "По статистике дай ровно 3 коротких практичных рекомендации на русском, "
                "каждая с новой строки, без нумерации и преамбулы.",
                messages=[{"role": "user", "content": f"Статистика платформы: {stats}"}],
            )
            if response.stop_reason != "refusal":
                text = next((b.text for b in response.content if b.type == "text"), "")
                ai_recs = [line.strip("•- ").strip() for line in text.splitlines() if line.strip()]
                if ai_recs:
                    recommendations = ai_recs[:3]
                    source = "claude"
        except Exception:
            logger.warning("Claude insights недоступны, отдаю rule-based")

    return {"stats": stats, "recommendations": recommendations, "source": source}
