"""Telegram-бот для пошуку вакансій на OLX з фільтрами та категоріями."""
import asyncio
import html
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv

from .categories import CATEGORIES, classify
from .db import DB
from .olx import Offer, find_city, search, search_category

load_dotenv()
logging.basicConfig(level=logging.INFO)

PAGE_SIZE = 5
SORTS = {"new": "🕒 Спочатку нові", "salary": "💰 Спочатку більша з/п"}

db = DB(os.getenv("DB_PATH", "olxbot.db"))
dp = Dispatcher()
http: aiohttp.ClientSession | None = None
# Кеш результатів останнього пошуку для пагінації: user_id -> список оголошень
last_results: dict[int, list[Offer]] = {}


class Form(StatesGroup):
    city = State()
    salary = State()
    exclude = State()
    query = State()


# ---------- Клавіатури ----------

def kb(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def main_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🔎 Категорії", "cats"), ("✍️ Свій запит", "query")],
        [("⚙️ Фільтри", "filters"), ("🔔 Підписки", "subs")],
    ])


def cats_menu() -> InlineKeyboardMarkup:
    keys = list(CATEGORIES)
    rows = [[(CATEGORIES[k]["title"], f"cat:{k}") for k in keys[i:i + 2]]
            for i in range(0, len(keys), 2)]
    return kb(rows + [[("⬅️ Меню", "menu")]])


def filters_text(s: dict) -> str:
    return ("<b>Ваші фільтри</b>\n"
            f"📍 Місто: {s['city_name'] or 'вся Україна'}\n"
            f"💰 Мін. з/п: {s['min_salary'] or 'будь-яка'}\n"
            f"↕️ Сортування: {SORTS[s['sort']]}\n"
            f"🚫 Виключити слова: {', '.join(s['exclude']) or '—'}")


def filters_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📍 Місто", "f:city"), ("💰 Мін. з/п", "f:salary")],
        [("↕️ Сортування", "f:sort"), ("🚫 Виключення", "f:exclude")],
        [("♻️ Скинути", "f:reset"), ("⬅️ Меню", "menu")],
    ])


def subs_menu(s: dict) -> InlineKeyboardMarkup:
    rows = [[(("✅ " if k in s["subs"] else "▫️ ") + c["title"], f"sub:{k}")]
            for k, c in CATEGORIES.items()]
    return kb(rows + [[("⬅️ Меню", "menu")]])


# ---------- Фільтрація та вивід ----------

def apply_filters(offers: list[Offer], s: dict) -> list[Offer]:
    out = []
    for o in offers:
        if s["min_salary"] and o.salary_value and o.salary_value < s["min_salary"]:
            continue
        text = f"{o.title} {o.description}".lower()
        if any(w in text for w in s["exclude"]):
            continue
        o.categories = classify(o.title, o.description)
        out.append(o)
    if s["sort"] == "salary":
        out.sort(key=lambda o: o.salary_value, reverse=True)
    else:
        out.sort(key=lambda o: o.created.timestamp() if o.created else 0, reverse=True)
    return out


def fmt_offer(o: Offer) -> str:
    tags = " ".join(CATEGORIES[c]["title"].split(" ", 1)[0] for c in o.categories)
    date = o.created.strftime("%d.%m %H:%M") if o.created else ""
    return (f"<b>{html.escape(o.title)}</b> {tags}\n"
            f"💰 {o.salary_text()}   📍 {html.escape(o.city)}   🕒 {date}\n"
            f"<a href=\"{o.url}\">Відкрити на OLX</a>")


async def show_page(target: Message, user_id: int, page: int, edit: bool = False):
    offers = last_results.get(user_id, [])
    if not offers:
        await target.answer("😕 Нічого не знайдено. Спробуйте змінити фільтри.",
                            reply_markup=main_menu())
        return
    pages = (len(offers) - 1) // PAGE_SIZE + 1
    chunk = offers[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    text = f"Знайдено: <b>{len(offers)}</b> (стор. {page + 1}/{pages})\n\n" + \
           "\n\n".join(fmt_offer(o) for o in chunk)
    nav = []
    if page > 0:
        nav.append(("◀️", f"page:{page - 1}"))
    if page < pages - 1:
        nav.append(("▶️", f"page:{page + 1}"))
    markup = kb([nav, [("⬅️ Меню", "menu")]] if nav else [[("⬅️ Меню", "menu")]])
    if edit:
        await target.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


# ---------- Хендлери ----------

@dp.message(CommandStart())
@dp.message(Command("menu"))
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("👋 Привіт! Я допоможу знайти роботу на OLX.\n"
                   "Оберіть категорію, задайте фільтри або підпишіться на нові вакансії.",
                   reply_markup=main_menu())


@dp.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("Головне меню:", reply_markup=main_menu())


@dp.callback_query(F.data == "cats")
async def cb_cats(c: CallbackQuery):
    await c.message.edit_text("Оберіть категорію:", reply_markup=cats_menu())


@dp.callback_query(F.data.startswith("cat:"))
async def cb_cat(c: CallbackQuery):
    key = c.data.split(":", 1)[1]
    s = db.get(c.from_user.id)
    await c.answer("Шукаю…")
    await c.message.edit_text(f"⏳ Шукаю: {CATEGORIES[key]['title']}…")
    offers = await search_category(http, CATEGORIES[key]["keywords"], city_id=s["city_id"])
    last_results[c.from_user.id] = apply_filters(offers, s)
    await show_page(c.message, c.from_user.id, 0, edit=True)


@dp.callback_query(F.data.startswith("page:"))
async def cb_page(c: CallbackQuery):
    await show_page(c.message, c.from_user.id, int(c.data.split(":")[1]), edit=True)
    await c.answer()


@dp.callback_query(F.data == "query")
async def cb_query(c: CallbackQuery, state: FSMContext):
    await state.set_state(Form.query)
    await c.message.edit_text("Введіть, яку роботу шукаєте (напр. «нічна зміна склад»):")


@dp.message(Form.query)
async def on_query(m: Message, state: FSMContext):
    await state.clear()
    s = db.get(m.from_user.id)
    offers = await search(http, m.text.strip(), city_id=s["city_id"])
    last_results[m.from_user.id] = apply_filters(offers, s)
    await show_page(m, m.from_user.id, 0)


# --- Фільтри ---

@dp.callback_query(F.data == "filters")
async def cb_filters(c: CallbackQuery):
    await c.message.edit_text(filters_text(db.get(c.from_user.id)), reply_markup=filters_menu())


@dp.callback_query(F.data == "f:sort")
async def cb_sort(c: CallbackQuery):
    s = db.get(c.from_user.id)
    s["sort"] = "salary" if s["sort"] == "new" else "new"
    db.save(c.from_user.id, s)
    await c.message.edit_text(filters_text(s), reply_markup=filters_menu())


@dp.callback_query(F.data == "f:reset")
async def cb_reset(c: CallbackQuery):
    s = db.get(c.from_user.id)
    s.update(city_id=None, city_name=None, min_salary=0, sort="new", exclude=[])
    db.save(c.from_user.id, s)
    await c.message.edit_text(filters_text(s), reply_markup=filters_menu())


@dp.callback_query(F.data == "f:city")
async def cb_city(c: CallbackQuery, state: FSMContext):
    await state.set_state(Form.city)
    await c.message.edit_text("Введіть назву міста (або «-» для всієї України):")


@dp.message(Form.city)
async def on_city(m: Message, state: FSMContext):
    s = db.get(m.from_user.id)
    if m.text.strip() == "-":
        s["city_id"] = s["city_name"] = None
    else:
        found = await find_city(http, m.text.strip())
        if not found:
            await m.answer("Місто не знайдено, спробуйте ще раз:")
            return
        s["city_id"], s["city_name"] = found
    db.save(m.from_user.id, s)
    await state.clear()
    await m.answer(filters_text(s), reply_markup=filters_menu())


@dp.callback_query(F.data == "f:salary")
async def cb_salary(c: CallbackQuery, state: FSMContext):
    await state.set_state(Form.salary)
    await c.message.edit_text("Введіть мінімальну зарплату в грн (0 — без обмеження):")


@dp.message(Form.salary)
async def on_salary(m: Message, state: FSMContext):
    digits = "".join(ch for ch in m.text if ch.isdigit())
    if not digits:
        await m.answer("Потрібне число, наприклад 15000:")
        return
    s = db.get(m.from_user.id)
    s["min_salary"] = int(digits)
    db.save(m.from_user.id, s)
    await state.clear()
    await m.answer(filters_text(s), reply_markup=filters_menu())


@dp.callback_query(F.data == "f:exclude")
async def cb_exclude(c: CallbackQuery, state: FSMContext):
    await state.set_state(Form.exclude)
    await c.message.edit_text("Слова через кому, які треба виключити "
                              "(напр. «вахта, за кордоном»), або «-» щоб очистити:")


@dp.message(Form.exclude)
async def on_exclude(m: Message, state: FSMContext):
    s = db.get(m.from_user.id)
    s["exclude"] = [] if m.text.strip() == "-" else \
        [w.strip().lower() for w in m.text.split(",") if w.strip()]
    db.save(m.from_user.id, s)
    await state.clear()
    await m.answer(filters_text(s), reply_markup=filters_menu())


# --- Підписки ---

@dp.callback_query(F.data == "subs")
async def cb_subs(c: CallbackQuery):
    await c.message.edit_text("🔔 Оберіть категорії — я надсилатиму нові вакансії "
                              "(з урахуванням ваших фільтрів):",
                              reply_markup=subs_menu(db.get(c.from_user.id)))


@dp.callback_query(F.data.startswith("sub:"))
async def cb_sub(c: CallbackQuery):
    key = c.data.split(":", 1)[1]
    s = db.get(c.from_user.id)
    if key in s["subs"]:
        s["subs"].remove(key)
    else:
        s["subs"].append(key)
        # Позначаємо поточні оголошення як вже бачені, щоб не засипати старими
        offers = await search_category(http, CATEGORIES[key]["keywords"], city_id=s["city_id"])
        db.mark_sent(c.from_user.id, [o.id for o in offers])
    db.save(c.from_user.id, s)
    await c.message.edit_reply_markup(reply_markup=subs_menu(s))
    await c.answer()


async def notifier(bot: Bot):
    interval = int(os.getenv("CHECK_INTERVAL_MIN", "15")) * 60
    while True:
        await asyncio.sleep(interval)
        for uid, s in db.subscribers():
            try:
                for key in s["subs"]:
                    offers = await search_category(http, CATEGORIES[key]["keywords"],
                                                   city_id=s["city_id"])
                    offers = apply_filters(offers, s)
                    new_ids = db.filter_unsent(uid, [o.id for o in offers])
                    for o in [o for o in offers if o.id in new_ids][:10]:
                        await bot.send_message(uid, "🆕 " + fmt_offer(o),
                                               disable_web_page_preview=True)
                    db.mark_sent(uid, new_ids)
            except Exception:
                logging.exception("notify failed for %s", uid)


async def main():
    global http
    bot = Bot(os.environ["BOT_TOKEN"], default=DefaultBotProperties(parse_mode="HTML"))
    async with aiohttp.ClientSession() as session:
        http = session
        asyncio.create_task(notifier(bot))
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
