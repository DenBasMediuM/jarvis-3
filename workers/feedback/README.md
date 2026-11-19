# jarvis-feedback (Cloudflare Worker) — модуль «Улучшения»

Заявки пользователей витрины → диалог с ИИ (уточнения, ≤3 раундов) → оформленная заявка →
дорожная карта в админке Jarvis → решение с комментарием, которое видит автор.

- **D1** (`DB`) — диалоги, заявки, голоса «+1», описание продукта (`meta.product`).
- **Авторизация** — Worker сам проверяет пароль по `docs/auth/users.json` (PBKDF2) и выдаёт
  подписанный токен (HMAC, 30 дней). Витрина получает его при входе.
- **ИИ** — OpenAI `gpt-4o-mini`, ключ только в секрете Worker (`OPENAI_BASE_URL` можно переопределить в vars).
- **Описание продукта** — `PRODUCT.md` в корне репо; Jarvis отправляет его в Worker (`PUT /admin/product`).

## Деплой (один раз)

```bash
cd workers/feedback
npx wrangler login
npx wrangler d1 create jarvis-feedback          # скопируйте database_id в wrangler.toml
npx wrangler d1 execute jarvis-feedback --remote --file=schema.sql
npx wrangler secret put OPENAI_API_KEY          # ключ OpenAI
npx wrangler secret put TOKEN_SECRET            # длинная случайная строка (openssl rand -hex 32)
npx wrangler secret put ADMIN_KEY               # длинная случайная строка — её же в .env Jarvis
npx wrangler deploy
```

В `.env` Jarvis:

```bash
JARVIS_FEEDBACK_URL=https://jarvis-feedback.<account>.workers.dev
JARVIS_FEEDBACK_ADMIN_KEY=<тот же ADMIN_KEY>
```

Обновление кода: `npx wrangler deploy`. Схема идемпотентна (`CREATE … IF NOT EXISTS`).

## API

| Метод | Путь | Кто | Что |
|---|---|---|---|
| POST | `/auth/login` | витрина | `{login,password}` → `{token}` |
| POST | `/conversations` | пользователь | новое пожелание `{message, context}` → ответ ИИ |
| POST | `/conversations/:id/messages` | пользователь | ответ на уточнения |
| POST | `/conversations/:id/submit` | пользователь | отправить (возможно поправленный) черновик |
| POST | `/requests/:id/vote` | пользователь | «+1» к похожей заявке вместо новой |
| GET | `/requests/mine` | пользователь | свои и поддержанные заявки со статусами |
| GET | `/admin/requests` | Jarvis | все заявки + оценка ИИ + переписка |
| PATCH | `/admin/requests/:id` | Jarvis | `{status, admin_comment, priority}` |
| PUT | `/admin/product` | Jarvis | `{markdown}` — описание продукта для ИИ |

Лимиты: 10 новых заявок в день на пользователя, 10 сообщений в диалоге, 2000 символов на сообщение.

Тесты чистых функций: `npm test` (Node ≥ 20).

## Раздел «Аутсорс мастера» (`src/outsource.js`)

Тот же Worker хранит воронку аутсорсеров: таблицы `outsource_candidates`, `outsource_trials`,
`outsource_log`, план — `meta.outsource_plan`. Доступ — токен входа витрины + доступ
`processes.outsource` (менеджер) или `processes.outsource_lead` (руководитель, может менять план).

Подключение (один раз, после обновления кода):

```bash
cd workers/feedback
npx wrangler d1 execute jarvis-feedback --remote --file=migrations/0002_outsource.sql
npx wrangler deploy
```

| Метод | Путь | Что |
|---|---|---|
| GET | `/outsource/state` | кандидаты, передачи, журнал (180 дн.), план, права |
| POST | `/outsource/candidates` | новый кандидат |
| PATCH | `/outsource/candidates/:id` | правка карточки |
| POST | `/outsource/candidates/:id/stage` | смена стадии (`lost` — с причиной) |
| POST | `/outsource/candidates/:id/note` | запись в журнал |
| POST | `/outsource/trials` | передача устройства (первая → стадия «Пробник») |
| POST | `/outsource/trials/:id/result` | оценка пробника (take → «Постоянный», reject → «Отказ») |
| PUT | `/outsource/plan` | недельный план и цель (руководитель) |
| GET | `/admin/outsource/state` | то же для Jarvis (`ADMIN_KEY`) |
