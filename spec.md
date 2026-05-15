# Spec: olcrtc-manager-bot

## Objective
Telegram-бот для управления olcrtc-сервером: генерация конфигов для друзей, запуск/остановка сервисов, мониторинг статуса. Замена SSH для быстрых операций.

**Пользователь:** только Леонтий (личный инструмент)
**Ценность:** не надо логиниться по SSH чтобы перезапустить сервер или выдать новый конфиг

## Core Features

1. **Генерация конфигов для друзей** — name, client-id, key, room_id (авто из Jazz `-id any`) → выдача готового конфига
2. **Просмотр конфигов** — список созданных для всех юзеров (админ видит все), копирование значений
3. **Управление сервисами** — запуск/остановка/рестарт/статус systemd-сервисов
4. **Мониторинг** — живой статус сервисов (systemctl is-active), последние логи (journalctl -n 5)

## Tech Stack
- Python 3.11+
- python-telegram-bot v20+
- SQLite (aiosqlite) — profiles, services
- systemd (systemctl через asyncio subprocess)
- olcrtc binary: /root/olcrtc-server/olcrtc

## Data Model (SQLite)

```sql
profiles:
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,           -- "Паша", "Дима", "Тестовый"
  client_id TEXT NOT NULL UNIQUE,
  key_hex TEXT NOT NULL,        -- 64 hex chars
  room_id TEXT,                 -- "ipx3ff:8ks21rcn" или просто id
  carrier TEXT DEFAULT 'jazz',
  transport TEXT DEFAULT 'datachannel',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  active INTEGER DEFAULT 0     -- 1 если сейчас запущен

services:
  id INTEGER PRIMARY KEY,
  profile_id INTEGER REFERENCES profiles(id),
  service_name TEXT NOT NULL,   -- systemd unit name
  status TEXT,                  -- active/inactive/failed
  last_check TIMESTAMP
```

## Commands

```
/start — главное меню с inline-кнопками
🆕 Новый конфиг — создаёт name, client-id, key, room_id (auto-gen Jazz)
📋 Конфиги — список созданных конфигов
▶️ Запустить — выбор конфига, systemctl start
⏹ Остановить — выбор сервиса, systemctl stop  
🔄 Статус — active/inactive/failed + последние 5 строк логов
```

## Inline Menu (state machine)

Главное меню:
```
[🆕 Новый конфиг] [📋 Конфиги] [▶️ Запустить] [⏹ Остановить] [🔄 Статус]
```

## Config Generation Flow

1. `openssl rand -hex 32` → key_hex
2. Ask name: «Для кого конфиг?» (Паша, Дима, …)
3. `olcrtc -mode srv -id any -carrier jazz -key <KEY> -client-id <NAME> -transport datachannel -link direct -dns 1.1.1.1:53 -data /root/olcrtc-server/data` → ловим «Jazz room created: XXXX:YYYY»
4. Убиваем процесс (он сделал своё дело — комната создана)
5. Сохраняем в SQLite
6. Показываем результат (key, room, client-id — каждый в отдельном `блоке`, имя текстом)

## Output Format (per user preference)

После генерации:
```
Конфиг для Паши

Ключ:
`abc123...`

Комната:
`ipx3ff:8ks21rcn`

Client ID:
`pasha`

Carrier: jazz
Transport: datachannel
```

## Access Control
- ALLOWED_USER_ID: configurable via .env
- Только один пользователь (Леонтий)
- Никто другой не может управлять ботом

## Boundaries

### Always Do
- Проверять Telegram ID (whitelist)
- Валидировать конфиги перед сохранением
- Логировать все systemctl-операции

### Ask First
- Удаление конфигов
- Массовая генерация (>1 за раз)

### Never Do
- Показывать конфиги неавторизованным
- Выполнять systemctl без проверки прав
- Сохранять дубликаты client-id

## Success Criteria

- /start рендерит меню < 1 секунды
- Генерация конфига < 30 секунд
- systemctl-команды < 5 секунд
- Конфиги персистентны между рестартами
- До 5 друзей + админ работают одновременно

## Open Questions (resolved)
1. ✅ Авторизация: Леонтий + до 5 whitelisted друзей
2. ✅ Генерация комнат: `-id any` с ловлей stdout
3. ✅ Планировщик: не нужен (ручное управление)
4. ⏳ Структура папок: одобрить ниже

## Project Structure (proposed)

```
/root/olcrtc-manager-bot/
├── bot.py              # entry point, handlers, state machine
├── database.py         # SQLite via aiosqlite
├── olcrtc.py           # subprocess wrapper: gen_key, gen_room, systemctl
├── config.py           # env vars, constants
├── spec.md             # этот файл
├── requirements.txt    # python-telegram-bot, aiosqlite
└── profiles.db         # SQLite (автосоздаётся)
```
