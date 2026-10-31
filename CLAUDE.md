# Jarvis — заметки для разработки

Карта и функциональность: `README.md` (запуск), `PRODUCT.md` (что умеет система — **обновлять
при любом изменении функциональности витрины/админки в том же коммите**; его читает ИИ модуля
«Улучшения»).

## Устройство
- `core/` — FastAPI (`core/main.py` — все эндпоинты), SQLite (`core/db.py`, миграции `_migrate_*`).
- `modules/<name>/` — бизнес-логика блоков (gincore, vyrobotka, reviews, buffer_quality, feedback…).
- `web/` — админка (один `static/app.js`). `docs/` — витрина GitHub Pages (статичная, данные — `data.json`).
- `workers/` — Cloudflare Workers: `debt-inbox`, `reviews-inbox` (KV), `feedback` (D1 + OpenAI).

## Правила
- Jarvis запускается без reload: после правок Python — перезапуск `python run.py`.
- При правке `web/static/app.js` / `docs/*/app.js` поднимать `?v=` в соответствующем `index.html`.
- В `docs/` нельзя класть секреты (репозиторий и Pages публичные). Персональные данные — минимум.
- Тесты: `pytest tests`, воркер feedback: `cd workers/feedback && npm test`.
- Публикация витрины: экспорт пишет `docs/*/data.json`; push — `POST /api/vyrobotka/publish-pages`
  (коммитит всё застейдженное).
