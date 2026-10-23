# jarvis-reviews-inbox (Cloudflare Worker)

Inbox сбора отзывов: витрина `POST /result`, `POST /google-stats`; Jarvis `GET /inbox` + `POST /inbox/ack`.

Очередь из 10 квитанций собирается **на витрине** из опубликованного пула кандидатов (`data.json`): обработали одну — подтягивается следующая из пула. Cloudflare хранит только результаты (KV), не CRM.

## Деплой

1. Workers & Pages → Create Worker **jarvis-reviews-inbox**.
2. Workers KV → Create namespace → bind as `INBOX`.
3. Settings → Variables → Secrets: `WRITE_KEY`, `READ_KEY` (длинные случайные строки).
4. Edit code → вставить [`src/index.js`](src/index.js) → Save and deploy.

В `.env` Jarvis:

```bash
JARVIS_REVIEWS_INBOX_URL=https://jarvis-reviews-inbox.<account>.workers.dev
JARVIS_REVIEWS_INBOX_WRITE_KEY=...
JARVIS_REVIEWS_INBOX_READ_KEY=...
```

## Бесплатные лимиты Cloudflare

- Dashboard → слева **Workers & Pages** → откройте Worker → вкладка **Metrics** (запросы за период).
- Лимиты плана: аватар аккаунта → **Billing** / **Plans and Billing** (Workers Free: суточный лимит запросов; KV — отдельные операции).
- Точный «остаток до лимита» через API только с Account Analytics + API token — в админке Jarvis показываем подсказку и результат последнего Inbox ingest.
