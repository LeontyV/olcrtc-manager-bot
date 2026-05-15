# Implementation Plan: olcrtc-manager-bot

## Overview
Telegram-бот на python-telegram-bot v20 с SQLite. Управление olcrtc-сервером через inline-кнопки. Один пользователь (Леонтий).

## Architecture Decisions
- **python-telegram-bot v20+** — async, ConversationHandler для state machine
- **aiosqlite** — async SQLite, без отдельного процесса
- **asyncio subprocess** — обёртка над openssl + olcrtc + systemctl
- **ConversationHandler** — ловит имя при создании конфига, остальное — CallbackQueryHandler

---

## Task List

### Phase 1: Foundation
*Build the skeleton — config, database, olcrtc subprocess wrapper.*

- [ ] **Task 1: config.py**  
  **Description:** Загрузка BOT_TOKEN из .env, константы (ALLOWED_USER_ID, пути к olcrtc).  
  **Acceptance:** `from config import BOT_TOKEN, OLCRTC_BIN` работает.  
  **Verify:** `python -c "from config import BOT_TOKEN; print(BOT_TOKEN[:5])"`  
  **Files:** `config.py`, `.env.example`  
  **Size:** XS

- [ ] **Task 2: database.py**  
  **Description:** SQLite через aiosqlite. Таблицы profiles + services. CRUD: create_profile, list_profiles, delete_profile, set_active. Инит при старте.  
  **Acceptance:** `await create_profile("Паша", "pasha", "abc...", "room:pass")` → запись в БД, `list_profiles()` → список.  
  **Verify:** `python -c "import asyncio; from database import init_db, create_profile, list_profiles; asyncio.run(init_db()); ..." `  
  **Files:** `database.py`  
  **Size:** S

- [ ] **Task 3: olcrtc.py**  
  **Description:** Async subprocess wrapper: `gen_key()` (openssl rand -hex 32), `gen_room(client_id, key)` (olcrtc -id any → ловит "room created"), `systemctl(action, service)`.  
  **Acceptance:** `gen_key()` → 64 hex chars, `gen_room("test", key)` → dict с room_id, `systemctl("start", "olcrtc-leo")` → (True, "").  
  **Verify:** Запустить функции вручную, проверить вывод.  
  **Files:** `olcrtc.py`  
  **Size:** S

### Checkpoint: Foundation
- [ ] Все три модуля импортируются без ошибок
- [ ] DB инициализируется, таблицы создаются
- [ ] `gen_key()` выдаёт 64 символа
- [ ] `gen_room()` создаёт комнату (требует доступ к Jazz API через WG)

---

### Phase 2: Core Features
*Бот с рабочими кнопками.*

- [ ] **Task 4: bot.py — /start + главное меню**  
  **Description:** Application builder, `/start` → главное меню с 5 inline-кнопками. Callback handlers-заглушки (отвечают "в разработке"). Фильтр по ALLOWED_USER_ID.  
  **Acceptance:** `/start` → меню с 5 кнопками, нажатие → ответ. Чужой user → игнор.  
  **Verify:** Запустить, написать `/start` → меню, нажать кнопки → ответы.  
  **Files:** `bot.py`, `config.py`  
  **Size:** M

- [ ] **Task 5: bot.py — Новый конфиг (ConversationHandler)**  
  **Description:** Кнопка «🆕 Новый конфиг» → бот спрашивает имя → ловит ответ → gen_key + gen_room → сохраняет в БД → показывает результат (каждое значение в отдельном \`блоке\`).  
  **Acceptance:** Нажал «Новый конфиг» → «Для кого?» → ответил «Паша» → получил key, room, client-id. Запись в БД.  
  **Verify:** Полный цикл создания конфига. Проверить БД.  
  **Files:** `bot.py`, `database.py`, `olcrtc.py`  
  **Size:** M

- [ ] **Task 6: bot.py — 📋 Конфиги + ⏹ Удалить**  
  **Description:** Кнопка «📋 Конфиги» → inline-список конфигов. При выборе → детали (key, room, client-id — копируемые блоки) + кнопка «Удалить». Удаление с подтверждением.  
  **Acceptance:** Список конфигов → выбрал конфиг → вижу ключ/комнату/client-id → «Удалить» → «точно?» → удалено.  
  **Verify:** Создать 2 конфига → список → детали → удалить один → список обновлён.  
  **Files:** `bot.py`, `database.py`  
  **Size:** M

- [ ] **Task 7: bot.py — ▶️ Запустить / ⏹ Остановить / 🔄 Статус**  
  **Description:** Кнопки «Запустить» и «Остановить» → inline-список конфигов → выбор → systemctl start/stop сервиса. «Статус» → systemctl is-active + journalctl -n 5 для каждого сервиса.  
  **Acceptance:** Запуск → сервис active. Остановка → inactive. Статус → active/failed + логи.  
  **Verify:** Запустить сервис через бота → `systemctl is-active` на сервере → active. Остановить → inactive.  
  **Files:** `bot.py`, `olcrtc.py`  
  **Size:** M

### Checkpoint: Core Features
- [ ] Все кнопки работают
- [ ] Генерация конфига → комната создаётся
- [ ] systemctl-команды выполняются
- [ ] Статус показывает реальные данные

---

### Phase 3: Deployment
*Запуск как systemd-сервис.*

- [ ] **Task 8: systemd-сервис**  
  **Description:** `olcrtc-manager.service` — systemd unit, venv, автостарт.  
  **Acceptance:** `systemctl start olcrtc-manager` → бот отвечает на /start.  
  **Verify:** `systemctl status olcrtc-manager` → active, бот в TG работает.  
  **Files:** `olcrtc-manager.service`  
  **Size:** XS

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Jazz API недоступен без WG | gen_room фейлится | Показывать ошибку, просить юзера проверить WG |
| olcrtc -id any не возвращает вывод сразу | gen_room таймаутит | Таймаут 30s, ловить stderr |
| systemctl требует sudo | Permission denied | Запускать бота под root (уже) |

## Open Questions
- [ ] Как называть systemd-сервисы? `olcrtc-{client_id}` или вручную через кнопку?
