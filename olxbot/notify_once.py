"""Одноразова перевірка нових вакансій і розсилка в Telegram.

Для запуску за розкладом (GitHub Actions) без постійного сервера.
Налаштування через змінні оточення:
  BOT_TOKEN, CHAT_ID       — обов'язкові (секрети)
  OLX_COUNTRY              — ua / pl
  CITY                     — назва міста (порожньо = вся країна)
  CATEGORIES               — ключі через кому або "all"
  MIN_SALARY               — мінімальна з/п (0 = будь-яка)
  EXCLUDE                  — слова-виключення через кому
  SENT_FILE                — файл з уже надісланими id
"""
import asyncio
import json
import os
from pathlib import Path

import aiohttp

from .categories import CATEGORIES
from .main import apply_filters, fmt_offer
from .olx import find_city, search_category

MAX_PER_RUN = 20
MAX_FIRST_RUN = 5


async def send(session, token: str, chat_id: str, text: str) -> None:
    async with session.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }) as r:
        if r.status != 200:
            print("Telegram error:", r.status, await r.text())
        await asyncio.sleep(0.5)


async def main():
    token, chat_id = os.environ["BOT_TOKEN"], os.environ["CHAT_ID"]
    cats = os.getenv("CATEGORIES", "all").strip()
    keys = list(CATEGORIES) if cats in ("", "all") else [c.strip() for c in cats.split(",")]
    settings = {
        "min_salary": int(os.getenv("MIN_SALARY") or 0),
        "exclude": [w.strip().lower() for w in os.getenv("EXCLUDE", "").split(",") if w.strip()],
        "sort": "new",
    }
    sent_path = Path(os.getenv("SENT_FILE", "sent.json"))
    first_run = not sent_path.exists()
    sent = set(json.loads(sent_path.read_text())) if not first_run else set()

    async with aiohttp.ClientSession() as session:
        city_id = None
        if city := os.getenv("CITY", "").strip():
            found = await find_city(session, city)
            if not found:
                raise SystemExit(f"Місто «{city}» не знайдено на OLX")
            city_id = found[0]

        offers = {}
        for key in keys:
            for o in await search_category(session, CATEGORIES[key]["keywords"], city_id=city_id):
                offers.setdefault(o.id, o)
        fresh = [o for o in apply_filters(list(offers.values()), settings) if o.id not in sent]
        print(f"Знайдено {len(offers)}, нових {len(fresh)}")

        to_send = fresh[:MAX_FIRST_RUN if first_run else MAX_PER_RUN]
        if first_run:
            await send(session, token, chat_id,
                       "✅ Бот підключено! Надсилатиму нові вакансії. Ось кілька останніх:")
        for o in reversed(to_send):  # старіші першими, найсвіжіша внизу
            await send(session, token, chat_id, "🆕 " + fmt_offer(o))

    # Запам'ятовуємо всі побачені (навіть не надіслані), щоб не було спаму старими
    sent |= {o.id for o in fresh}
    sent_path.write_text(json.dumps(sorted(sent)[-5000:]))


if __name__ == "__main__":
    asyncio.run(main())
