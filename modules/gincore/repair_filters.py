"""CRM repair-order filters: catalogs, fuzzy resolve, URL param mapping."""

from __future__ import annotations

import re
from typing import Any


# CRM short query keys (from POST /orders apply-filter redirects).
# Form field → URL: status[]→st, engineers[]→eng, managers[]→mg, accepter[]→acp,
# department[]→dep, repair[]→rep, other[]→other, person[]→person, client→cl,
# order_id→co_id, date→df/dt, date-type→date-type, hm_date→hmd, from/to→from/to.

STATUSES: dict[str, str] = {
    "0": "Принят в ремонт",
    "2": "На диагностике",
    "5": "В процессе ремонта",
    "10": "Ожидает запчастей",
    "15": "Клиент отказался",
    "20": "Не подлежит ремонту",
    "25": "Выдан без ремонта",
    "27": "На согласовании",
    "30": "В удаленном сервисе",
    "35": "Готов",
    "36": "Готов частично",
    "40": "Выдан",
    "45": "Принят на доработку",
    "50": "Переведен в донор",
    "51": "Не дозвонились",
    "52": "Ждем оплату",
    "53": "Ждем запч с Китая",
    "54": "На продажу",
    "55": "У курьера ГОТОВ",
    "56": "У курьера БЕЗ РЕМОНТ",
    "59": "Перемещен на склад",
    "60": "Собираем на возврат",
    "61": "обработано ботом",
    "64": "Собран на возврат",
    "65": "На тесте",
}

REPAIR_TYPES: dict[str, str] = {
    "4": "Платный",
    "7": "Доработка",
    "1": "Гарантийный Canon",
    "2": "Гарантийный Ricoh",
}

PERSON_TYPES: dict[str, str] = {
    "1": "Физ. лицо",
    "2": "Юр. лицо",
}

OTHER_FLAGS: dict[str, str] = {
    "hmr": "Вызов мастера на дом",
    "cgd": "Устройство забрал курьер",
    "np": "Принято через почту",
    "urgent": "Срочные",
    "pay": "Оплачены не полностью",
    "rf": "Выдан подменный фонд",
    "nm": "Неоплаченные заказы",
    "ar": "Принимались на доработку",
    "att": "Содержат вложения",
}

# Static department catalog (id → label). Dynamic staff lists come from CRM.
DEPARTMENTS: dict[str, str] = {
    "1-a": "Принят: СЦ Каретный",
    "1-l": "Находится: СЦ Каретный",
    "3-a": "Принят: СЦ Сахарова",
    "3-l": "Находится: СЦ Сахарова",
    "9-a": "Принят: СЦ Небесної сотні",
    "9-l": "Находится: СЦ Небесної сотні",
    "13-a": "Принят: СЦ Сегедская",
    "13-l": "Находится: СЦ Сегедская",
    "19-a": "Принят: СЦ Вознесенский",
    "19-l": "Находится: СЦ Вознесенский",
    "20-a": "Принят: СЦ Каретный АРХИВ",
    "20-l": "Находится: СЦ Каретный АРХИВ",
    "23-a": "Принят: СЦ Каретный СКЛАД",
    "23-l": "Находится: СЦ Каретный СКЛАД",
    "26-a": "Принят: СЦ Радужный",
    "26-l": "Находится: СЦ Радужный",
    "31-a": "Принят: СЦ Левитан",
    "31-l": "Находится: СЦ Левитан",
    "34-a": "Принят: СЦ Екатерининская",
    "34-l": "Находится: СЦ Екатерининская",
    "37-a": "Принят: СЦ Пушкинская",
    "37-l": "Находится: СЦ Пушкинская",
    "l-l": "Находится в Логистике",
}

DATE_TYPES: dict[str, str] = {
    "": "Принят в ремонт",
    "accepted": "Принят в ремонт",
    "issued": "Выдан из ремонта",
    "ready": "Переведен в готовые",
}


def _norm(text: str) -> str:
    s = (text or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s/+-]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _score(query: str, label: str) -> int:
    q, lab = _norm(query), _norm(label)
    if not q or not lab:
        return 0
    if q == lab:
        return 100
    if lab.startswith(q) or q.startswith(lab):
        return 90
    if q in lab:
        return 80
    q_tokens = q.split()
    if q_tokens and all(t in lab for t in q_tokens):
        return 70
    # surname-only match against "Имя Фамилия" / "Фамилия Имя"
    if len(q_tokens) == 1 and any(t.startswith(q_tokens[0]) for t in lab.split()):
        return 60
    return 0


def resolve_from_map(query: str, mapping: dict[str, str]) -> tuple[str, str] | None:
    """Return (id, label) best fuzzy match against id→label map."""
    q = (query or "").strip()
    if not q:
        return None
    if q in mapping:
        return q, mapping[q]
    # match by exact normalized label
    best: tuple[int, str, str] | None = None
    for vid, label in mapping.items():
        if _norm(vid) == _norm(q):
            return vid, label
        sc = _score(q, label)
        if sc and (best is None or sc > best[0]):
            best = (sc, vid, label)
    if best and best[0] >= 60:
        return best[1], best[2]
    return None


def resolve_status(query: str) -> tuple[str, str] | None:
    q = (query or "").strip()
    if not q:
        return None
    aliases = {
        "удаленный сервис": "30",
        "удалённый сервис": "30",
        "в удаленном сервисе": "30",
        "в удалённом сервисе": "30",
        "удаленном": "30",
        "удалённом": "30",
        "remote": "30",
        "диагностика": "2",
        "на диагностике": "2",
        "в работе": "5",
        "в процессе": "5",
        "готов": "35",
        "выдан": "40",
        "принят": "0",
        "принят в ремонт": "0",
    }
    nq = _norm(q)
    for k, vid in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        kn = _norm(k)
        if kn == nq or kn in nq or nq in kn:
            return vid, STATUSES[vid]
    return resolve_from_map(q, STATUSES)


def resolve_department(
    query: str,
    *,
    mode: str | None = None,
) -> tuple[str, str] | None:
    """
    Resolve location/branch.
    mode: 'l' = находится (default), 'a' = принят, None = infer from query.
    """
    q = (query or "").strip()
    if not q:
        return None
    nq = _norm(q)
    if nq in {"логистика", "в логистике", "логистике"}:
        return "l-l", DEPARTMENTS["l-l"]

    prefer = mode
    if prefer is None:
        if "принят" in nq:
            prefer = "a"
        elif "находит" in nq or "сейчас" in nq or "на точке" in nq:
            prefer = "l"
        else:
            prefer = "l"

    # Direct id
    if q in DEPARTMENTS:
        return q, DEPARTMENTS[q]

    best: tuple[int, str, str] | None = None
    for vid, label in DEPARTMENTS.items():
        suffix = vid.split("-")[-1]
        if prefer and suffix not in {prefer, "l"} and vid != "l-l":
            # still allow match but prefer correct suffix
            pass
        sc = _score(q, label)
        # boost branch name without prefix
        branch = re.sub(r"^(принят|находится):\s*сц\s*", "", _norm(label))
        sc = max(sc, _score(q, branch))
        if prefer and suffix == prefer:
            sc += 15
        elif prefer and suffix != prefer and vid != "l-l":
            sc -= 5
        if sc and (best is None or sc > best[0]):
            best = (sc, vid, label)
    if best and best[0] >= 60:
        return best[1], best[2]
    return None


def resolve_staff(query: str, options: list[dict[str, str]]) -> tuple[str, str] | None:
    """options: [{id, name}, ...] from CRM filter form."""
    q = (query or "").strip()
    if not q:
        return None
    if re.fullmatch(r"-?\d+", q):
        for o in options:
            if o["id"] == q:
                return o["id"], o["name"]
        return q, q
    best: tuple[int, str, str] | None = None
    for o in options:
        sc = _score(q, o["name"])
        if sc and (best is None or sc > best[0]):
            best = (sc, o["id"], o["name"])
    if best and best[0] >= 60:
        return best[1], best[2]
    return None


def resolve_repair_type(query: str) -> tuple[str, str] | None:
    q = (query or "").strip()
    aliases = {
        "платный": "4",
        "доработка": "7",
        "гарантийный": "1",
        "гарантия": "1",
        "canon": "1",
        "ricoh": "2",
    }
    nq = _norm(q)
    for k, vid in aliases.items():
        if k == nq or k in nq:
            return vid, REPAIR_TYPES[vid]
    return resolve_from_map(q, REPAIR_TYPES)


def resolve_person(query: str) -> tuple[str, str] | None:
    q = (query or "").strip()
    nq = _norm(q)
    if nq in {"физ", "физлицо", "физ лицо", "физ. лицо", "частное", "частник", "1"}:
        return "1", PERSON_TYPES["1"]
    if nq in {"юр", "юрлицо", "юр лицо", "юр. лицо", "компания", "организация", "2"}:
        return "2", PERSON_TYPES["2"]
    return resolve_from_map(q, PERSON_TYPES)


def resolve_other(query: str) -> tuple[str, str] | None:
    q = (query or "").strip()
    aliases = {
        "срочн": "urgent",
        "urgent": "urgent",
        "курьер": "cgd",
        "почт": "np",
        "нова пошта": "np",
        "на дом": "hmr",
        "вызов мастера": "hmr",
        "подменн": "rf",
        "неоплачен": "nm",
        "не полностью": "pay",
        "вложен": "att",
        "доработк": "ar",
    }
    nq = _norm(q)
    for k, vid in aliases.items():
        if k in nq or nq in k:
            return vid, OTHER_FLAGS[vid]
    return resolve_from_map(q, OTHER_FLAGS)


def resolve_date_type(query: str | None) -> str:
    if not query:
        return ""
    nq = _norm(query)
    if nq in {"issued", "выдан", "выдача", "выдан из ремонта"}:
        return "issued"
    if nq in {"ready", "готов", "переведен в готовые", "готовые"}:
        return "ready"
    return ""


def build_crm_params(
    *,
    filters: dict[str, Any],
    staff: dict[str, list[dict[str, str]]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Build CRM query params + resolved labels + post_filters (client-side).

    Returns (crm_params, resolved, post_filters).
    post_filters may include channel (рекламный канал) — нет в CRM filter form.
    """
    staff = staff or {}
    crm: dict[str, Any] = {}
    resolved: dict[str, Any] = {}
    post: dict[str, Any] = {}

    current = bool(filters.get("current"))
    status_q = filters.get("status")
    if isinstance(status_q, list):
        ids: list[str] = []
        labels: list[str] = []
        for item in status_q:
            hit = resolve_status(str(item))
            if hit:
                ids.append(hit[0])
                labels.append(hit[1])
        if ids:
            crm["st"] = ",".join(ids)
            resolved["status"] = labels
    elif status_q:
        hit = resolve_status(str(status_q))
        if hit:
            crm["st"] = hit[0]
            resolved["status"] = hit[1]

    # current / active open repairs — only if status not set to a concrete id
    if current and "st" not in crm:
        crm["st"] = "repair"
        resolved["current"] = True

    eng_q = filters.get("engineer")
    if eng_q:
        hit = resolve_staff(str(eng_q), staff.get("engineers") or [])
        if hit:
            crm["eng"] = hit[0]
            resolved["engineer"] = hit[1]
        else:
            # fallback: CRM text quick-search
            crm["engineer"] = str(eng_q).strip()
            resolved["engineer"] = str(eng_q).strip()

    for key, crm_key, bucket in (
        ("manager", "mg", "managers"),
        ("accepter", "acp", "accepters"),
    ):
        q = filters.get(key)
        if not q:
            continue
        hit = resolve_staff(str(q), staff.get(bucket) or [])
        if hit:
            crm[crm_key] = hit[0]
            resolved[key] = hit[1]
        else:
            # text quick-search aliases that work without id
            crm[key if key != "accepter" else "accepter"] = str(q).strip()
            resolved[key] = str(q).strip()

    loc_q = filters.get("location") or filters.get("department") or filters.get("branch")
    if loc_q:
        mode = filters.get("location_mode")  # 'a' | 'l' | None
        hit = resolve_department(str(loc_q), mode=mode)
        if hit:
            crm["dep"] = hit[0]
            resolved["location"] = hit[1]

    rt = filters.get("repair_type") or filters.get("repair")
    if rt:
        hit = resolve_repair_type(str(rt))
        if hit:
            crm["rep"] = hit[0]
            resolved["repair_type"] = hit[1]

    person = filters.get("person") or filters.get("person_type")
    if person:
        hit = resolve_person(str(person))
        if hit:
            crm["person"] = hit[0]
            resolved["person"] = hit[1]

    other = filters.get("other") or filters.get("flag")
    if other:
        hit = resolve_other(str(other))
        if hit:
            crm["other"] = hit[0]
            resolved["other"] = hit[1]

    if filters.get("client"):
        crm["cl"] = str(filters["client"]).strip()
        resolved["client"] = crm["cl"]
    if filters.get("order_id"):
        crm["co_id"] = str(filters["order_id"]).strip()
        resolved["order_id"] = crm["co_id"]
    if filters.get("serial"):
        crm["serial"] = str(filters["serial"]).strip()
        resolved["serial"] = crm["serial"]
    if filters.get("device"):
        crm["device"] = str(filters["device"]).strip()
        resolved["device"] = crm["device"]
    if filters.get("defect"):
        crm["defect"] = str(filters["defect"]).strip()
        resolved["defect"] = crm["defect"]
    if filters.get("comment"):
        crm["comment"] = str(filters["comment"]).strip()
        resolved["comment"] = crm["comment"]

    if filters.get("price_from") is not None and filters.get("price_from") != "":
        crm["from"] = str(filters["price_from"])
        resolved["price_from"] = crm["from"]
    if filters.get("price_to") is not None and filters.get("price_to") != "":
        crm["to"] = str(filters["price_to"])
        resolved["price_to"] = crm["to"]

    dt = resolve_date_type(filters.get("date_type"))
    if dt:
        crm["date-type"] = dt
        resolved["date_type"] = DATE_TYPES.get(dt, dt)

    # Рекламный канал — только post-filter (нет в CRM filter form).
    channel = filters.get("channel") or filters.get("ad_channel") or filters.get("source")
    if channel:
        post["channel"] = str(channel).strip()
        resolved["channel"] = post["channel"]

    return crm, resolved, post


def match_channel(order_channel: str, query: str) -> bool:
    return _score(query, order_channel or "") >= 60


def filter_orders_local(
    orders: list[dict[str, Any]], post_filters: dict[str, Any]
) -> list[dict[str, Any]]:
    out = orders
    ch = post_filters.get("channel")
    if ch:
        out = [o for o in out if match_channel(str(o.get("channel") or ""), ch)]
    return out
