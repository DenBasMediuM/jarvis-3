"""Реестр мастеров и константы Drive."""

from __future__ import annotations

ROOT_FOLDER_ID = "1O7nvvDD6S03X8wH97oMFR3jsdMyLFmMY"
DUBOVOY_FOLDER_ID = "1Fx6rOk0tbkDL3Mww9Bj8ahmM3OkXyMbS"
ZNAYDENOV_SPREADSHEET_ID = "1ZLv8VDpoMpZS7E85ECcF6MUxobmbM-HeqtwR2YW88qU"

# Папки Drive, которые не берём в статистику.
SKIP_FOLDER_NAMES = {
    "Коноваленко Владимир",
    "Нахаба Илья",
    "Тех. отдел Левитан",
}

# Явный набор «актуальных» мастеров (фамилия в lower).
FOCUS_SURNAMES = {
    "галанчук",
    "сатаулов",
    "плачковский",
    "руднев",
    "ефимов",
    "свидерко",
    "тарасенко",
    "садоян",
    "вовчук",
    "дубовой",
    "знайденов",
    "знайдёнов",
}

SKIP_SURNAMES = {
    "коноваленко",
    "нахаба",
}

# Стабильные ключи + цвета для графиков.
MASTER_META: dict[str, dict[str, str]] = {
    "galanchuk": {"surname": "галанчук", "color": "#0f6e56", "title": "Галанчук"},
    "sataulov": {"surname": "сатаулов", "color": "#1a5f8a", "title": "Сатаулов"},
    "plachkovskiy": {"surname": "плачковский", "color": "#8a4b1a", "title": "Плачковский"},
    "rudnev": {"surname": "руднев", "color": "#6b3fa0", "title": "Руднев"},
    "efimov": {"surname": "ефимов", "color": "#b45309", "title": "Ефимов"},
    "sviderko": {"surname": "свидерко", "color": "#0e7490", "title": "Свидерко"},
    "tarasenko": {"surname": "тарасенко", "color": "#be123c", "title": "Тарасенко"},
    "sadoyan": {"surname": "садоян", "color": "#4338ca", "title": "Садоян"},
    "vovchuk": {"surname": "вовчук", "color": "#047857", "title": "Вовчук"},
    "dubovoy": {"surname": "дубовой", "color": "#9a3412", "title": "Дубовой"},
    "znaydenov": {"surname": "знайденов", "color": "#334155", "title": "Знайденов"},
}

SURNAME_TO_KEY = {
    meta["surname"]: key for key, meta in MASTER_META.items()
}
SURNAME_TO_KEY["знайдёнов"] = "znaydenov"

COPY_NAME_MARKERS = ("для копии", "для копий", "копия", "шаблон", "пример")
