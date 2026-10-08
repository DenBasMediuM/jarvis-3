# Jarvis

Локальный личный ассистент с ИИ и подключаемыми модулями.

Сейчас работает на вашем компьютере. Модули можно добавлять отдельно (пока на Python; позже — и на других языках через общий протокол tools/HTTP).

## Быстрый старт

```bash
cd /Users/denis/apps/jarvis-3
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Откройте [http://127.0.0.1:8787](http://127.0.0.1:8787).

### 1. Настройки ИИ

Вкладка **ИИ** — любой OpenAI-совместимый API.

По умолчанию ожидается локальный [Ollama](https://ollama.com):

```bash
ollama pull llama3.2
ollama serve
```

Можно указать OpenAI / другой endpoint и API key.

### 2. Модуль Gincore

CRM: [https://itserviceoutsourcing.gincore.net/](https://itserviceoutsourcing.gincore.net/)

В **Модули → Gincore CRM** укажите:

- URL (уже подставлен ваш инстанс)
- логин
- пароль

Пароль хранится локально в `data/` в зашифрованном виде. Нажмите **Проверить вход**.

Примеры вопросов в чате:

- «Сколько в этом месяце выплачено з/п Юре Дубовому?»
- «Построй график затрат на хозяйственные расходы за текущий год»
- «Дай небольшую сводку важной аналитики за прошлый год»

## Архитектура

```
jarvis-3/
  core/           # FastAPI, чат, LLM tool-calling, БД
  modules/
    gincore/      # CRM: логин по сессии + tools для ИИ
  web/            # UI
  data/           # sqlite + ключ шифрования (локально, в .gitignore)
```

ИИ вызывает tools модулей (`gincore_salary`, `gincore_expenses`, …).  
У Gincore нет полноценного публичного read-API для финансов, поэтому модуль входит по логину/паролю и читает **кассы** и **транзакции** через внутренний tab-load API.

Считает суммы **локально** (с пагинацией и лимитом страниц). В модель ИИ уходят только итоги и небольшой sample — без тысяч сырых строк.

Примеры:
- зарплата сотруднику = сумма статьи «Зарплаты» по контрагенту за период
- хозтовары / аренда = сумма по соответствующей статье

## Переменные окружения (опционально)

Создайте файл `.env` в корне проекта (можно скопировать `.env.example`):

```bash
JARVIS_HOST=127.0.0.1
JARVIS_PORT=8787
JARVIS_LLM_BASE_URL=http://127.0.0.1:11434/v1
JARVIS_LLM_API_KEY=ollama
JARVIS_LLM_MODEL=llama3.2

# Telegram (кнопка «Отправить в ТГ текущий анализ»)
JARVIS_TELEGRAM_BOT_TOKEN=123456:ABC...   # токен от @BotFather
JARVIS_TELEGRAM_CHAT_ID=-1001234567890    # id чата / группы
```

После правок `.env` перезапустите `python run.py`.
