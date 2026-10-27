"""Клієнт публічного API OLX.ua (розділ «Робота»)."""
import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

COUNTRY = os.getenv("OLX_COUNTRY", "ua").lower()
DOMAIN = {"ua": "www.olx.ua", "pl": "www.olx.pl"}[COUNTRY]
API_URL = f"https://{DOMAIN}/api/v1/offers/"
# Розділ «Робота» / «Praca»
JOBS_CATEGORY_ID = {"ua": 6, "pl": 4}[COUNTRY]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "pl-PL,pl;q=0.9" if COUNTRY == "pl" else "uk-UA,uk;q=0.9",
}


@dataclass
class Offer:
    id: int
    title: str
    url: str
    city: str
    created: datetime | None
    salary_from: float | None
    salary_to: float | None
    currency: str
    description: str = ""
    categories: list[str] = field(default_factory=list)

    @property
    def salary_value(self) -> float:
        """Значення для сортування/фільтрації (верхня межа, якщо є)."""
        return self.salary_to or self.salary_from or 0

    def salary_text(self) -> str:
        if not (self.salary_from or self.salary_to):
            return "з/п не вказана"
        if self.salary_from and self.salary_to and self.salary_from != self.salary_to:
            return f"{self.salary_from:,.0f}–{self.salary_to:,.0f} {self.currency}".replace(",", " ")
        return f"{self.salary_value:,.0f} {self.currency}".replace(",", " ")


def _parse(raw: dict) -> Offer:
    salary_from = salary_to = None
    currency = "грн"
    for p in raw.get("params", []):
        if p.get("key") == "salary":
            v = p.get("value") or {}
            salary_from, salary_to = v.get("from"), v.get("to")
            currency = {"UAH": "грн", "PLN": "zł"}.get(v.get("currency"), v.get("currency") or "грн")
    loc = raw.get("location") or {}
    created = raw.get("created_time") or raw.get("last_refresh_time")
    try:
        created_dt = datetime.fromisoformat(created) if created else None
    except ValueError:
        created_dt = None
    return Offer(
        id=raw["id"],
        title=raw.get("title", "").strip(),
        url=raw.get("url", ""),
        city=(loc.get("city") or {}).get("name", ""),
        created=created_dt,
        salary_from=salary_from,
        salary_to=salary_to,
        currency=currency,
        description=raw.get("description", "") or "",
    )


async def search(session: aiohttp.ClientSession, query: str, *,
                 city_id: int | None = None, limit: int = 40) -> list[Offer]:
    params = {
        "offset": 0, "limit": limit, "category_id": JOBS_CATEGORY_ID,
        "query": query, "sort_by": "created_at:desc",
    }
    if city_id:
        params["city_id"] = city_id
    async with session.get(API_URL, params=params, headers=HEADERS,
                           timeout=aiohttp.ClientTimeout(total=20)) as r:
        if r.status != 200:
            return []
        data = await r.json(content_type=None)
    return [_parse(o) for o in data.get("data", [])]


async def find_city(session: aiohttp.ClientSession, name: str) -> tuple[int, str] | None:
    """Шукає місто за назвою через автопідказки OLX."""
    url = f"https://{DOMAIN}/api/v1/geo-encoder/location-autocomplete/"
    async with session.get(url, params={"query": name}, headers=HEADERS,
                           timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status != 200:
            return None
        data = await r.json(content_type=None)
    for item in data.get("data", []):
        city = item.get("city")
        if city:
            return city["id"], city.get("name", name)
    return None


async def search_category(session, keywords: list[str], *, city_id=None) -> list[Offer]:
    """Шукає по всіх ключових словах категорії, без дублікатів."""
    results = await asyncio.gather(
        *(search(session, kw, city_id=city_id) for kw in keywords), return_exceptions=True)
    seen: dict[int, Offer] = {}
    for res in results:
        if isinstance(res, Exception):
            continue
        for o in res:
            seen.setdefault(o.id, o)
    return list(seen.values())
