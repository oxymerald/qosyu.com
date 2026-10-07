from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from config import settings
from dependencies import get_current_user
from security import rate_limit
from services import dgis

router = APIRouter(prefix="/maps", tags=["maps"])


@router.get("/status")
async def status():
    return {"provider": "2gis" if settings.DGIS_API_KEY else "osm",
            "geocoder": bool(settings.DGIS_API_KEY)}


@router.get("/search", dependencies=[Depends(rate_limit("map-search", 30, 60))])
async def search(q: str = Query(min_length=3, max_length=250), _=Depends(get_current_user)):
    return {"provider": "2gis", "items": await dgis.geocode(q.strip())}


@router.get("/tiles/{z}/{x}/{y}.png", dependencies=[Depends(rate_limit("map-tiles", 600, 60))])
async def tile(z: int, x: int, y: int, _=Depends(get_current_user)):
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(422, "Некорректные координаты карты")
    result = await dgis.request("GET", f"https://tile0.maps.2gis.com/v2/tiles/online_sd/{z}/{x}/{y}.png")
    if not result.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(502, "2ГИС не вернул изображение карты. Проверьте Raster Tiles API.")
    return Response(result.content, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
