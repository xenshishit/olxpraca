"""Категорії вакансій: назва -> ключові слова для пошуку та класифікації.

Ключові слова залежать від країни OLX (змінна оточення OLX_COUNTRY: ua або pl).
"""
import os

COUNTRY = os.getenv("OLX_COUNTRY", "ua").lower()

CATEGORIES_UA: dict[str, dict] = {
    "zavod": {"title": "🏭 Завод / виробництво",
              "keywords": ["завод", "виробництво", "оператор верстата", "різноробочий", "фабрика", "цех"]},
    "sklad": {"title": "📦 Склад",
              "keywords": ["склад", "комплектувальник", "вантажник", "кладовщик", "комірник", "пакувальник"]},
    "kasyr": {"title": "🛒 Касир / продавець",
              "keywords": ["касир", "продавець", "продавець-консультант", "супермаркет"]},
    "vodiy": {"title": "🚚 Водій / кур'єр",
              "keywords": ["водій", "кур'єр", "доставка", "експедитор", "таксі"]},
    "budivnytstvo": {"title": "🏗 Будівництво",
                     "keywords": ["будівельник", "муляр", "штукатур", "електрик", "зварювальник", "сантехнік"]},
    "horeca": {"title": "🍽 Кафе / ресторан",
               "keywords": ["офіціант", "кухар", "бармен", "бариста", "посудомийниця"]},
    "prybyrannia": {"title": "🧹 Прибирання",
                    "keywords": ["прибиральниця", "прибирання", "клінінг", "покоївка"]},
    "okhorona": {"title": "🛡 Охорона",
                 "keywords": ["охоронник", "охорона", "сторож", "вахтер"]},
    "ofis": {"title": "💼 Офіс / менеджер",
             "keywords": ["менеджер", "оператор call", "адміністратор", "бухгалтер", "секретар"]},
}

CATEGORIES_PL: dict[str, dict] = {
    "zavod": {"title": "🏭 Завод / виробництво",
              "keywords": ["produkcja", "fabryka", "pracownik produkcji", "operator maszyn", "zakład"]},
    "sklad": {"title": "📦 Склад",
              "keywords": ["magazyn", "magazynier", "kompletacja", "pakowanie", "wózek widłowy"]},
    "kasyr": {"title": "🛒 Касир / продавець",
              "keywords": ["kasjer", "sprzedawca", "sklep", "kasjer-sprzedawca"]},
    "vodiy": {"title": "🚚 Водій / кур'єр",
              "keywords": ["kierowca", "kurier", "dostawca", "kierowca kat. b"]},
    "budivnytstvo": {"title": "🏗 Будівництво",
                     "keywords": ["budowa", "budowlaniec", "murarz", "elektryk", "spawacz", "hydraulik"]},
    "horeca": {"title": "🍽 Кафе / ресторан",
               "keywords": ["kelner", "kucharz", "barman", "barista", "pomoc kuchenna", "zmywak"]},
    "prybyrannia": {"title": "🧹 Прибирання",
                    "keywords": ["sprzątanie", "sprzątaczka", "pokojówka", "osoba sprzątająca"]},
    "okhorona": {"title": "🛡 Охорона",
                 "keywords": ["ochrona", "ochroniarz", "pracownik ochrony", "portier"]},
    "ofis": {"title": "💼 Офіс / менеджер",
             "keywords": ["biuro", "recepcjonista", "konsultant", "księgowa", "asystent"]},
}

CATEGORIES = CATEGORIES_PL if COUNTRY == "pl" else CATEGORIES_UA


def classify(title: str, description: str = "") -> list[str]:
    """Повертає ключі категорій, до яких підходить оголошення."""
    text = f"{title} {description}".lower()
    return [key for key, c in CATEGORIES.items()
            if any(kw.lower() in text for kw in c["keywords"])]
