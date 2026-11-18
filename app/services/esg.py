from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select

from models import CollectionZone, WasteRequest, WasteType
from services.collection_access import zone_has_request

# Model parameter, kg CO₂e per kg of cardboard. It is not a measured result.
CARDBOARD_CO2E_PER_KG = 0.315
CO2E_FORMULA_RU = (
    f"Расчётный модельный эквивалент: масса картона × {str(CARDBOARD_CO2E_PER_KG).replace('.', ',')} кг CO₂-экв./кг."
)


def calculate_co2_saved(cardboard_kg: float) -> float:
    equivalent = Decimal(str(cardboard_kg)) * Decimal(str(CARDBOARD_CO2E_PER_KG))
    return float(equivalent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def collected_weights_query():
    cardboard = case((WasteRequest.waste_type == WasteType.CARDBOARD, WasteRequest.weight_kg), else_=0)
    return select(func.coalesce(func.sum(WasteRequest.weight_kg), 0), func.coalesce(func.sum(cardboard), 0))


async def zone_cardboard_weights(db, zone_ids):
    query = (
        select(CollectionZone.id, func.sum(WasteRequest.weight_kg))
        .join(WasteRequest, zone_has_request())
        .where(CollectionZone.id.in_(zone_ids), WasteRequest.waste_type == WasteType.CARDBOARD)
        .group_by(CollectionZone.id)
    )
    return dict((await db.execute(query)).all())
