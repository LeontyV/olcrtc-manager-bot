"""
olcrtc-manager-bot — Telegram bot to manage olcrtc server.
Generates configs for friends, controls systemd services, shows status.
"""
import asyncio
import logging
import os
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes,
)
from telegram.error import Forbidden

from config import BOT_TOKEN, ALLOWED_USER_ID
from database import (
    init_db, create_profile, list_profiles, get_profile,
    delete_profile, set_profile_active,
)
from olcrtc import gen_key, gen_room, systemctl, journalctl, create_service

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ConversationHandler states
ASK_NAME = 1

# Callback data prefixes
CB_NEW = "new"
CB_LIST = "list"
CB_DETAIL = "detail"
CB_DELETE = "delete"
CB_CONFIRM_DELETE = "confirm_del"
CB_START = "start"
CB_STOP = "stop"
CB_STATUS = "status"

# ----- Access control -----

def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == ALLOWED_USER_ID

# ----- Menu -----

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Новый конфиг", callback_data=CB_NEW)],
        [InlineKeyboardButton("📋 Конфиги", callback_data=CB_LIST)],
        [InlineKeyboardButton("▶️ Запустить", callback_data=CB_START)],
        [InlineKeyboardButton("⏹ Остановить", callback_data=CB_STOP)],
        [InlineKeyboardButton("🔄 Статус", callback_data=CB_STATUS)],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "Управление olcrtc-сервером:",
        reply_markup=main_menu_keyboard(),
    )

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = "Меню"):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text, reply_markup=main_menu_keyboard())

# ----- Состояния -----
ASK_CARRIER, ASK_NAME, ASK_ROOM, ASK_TRANSPORT, GEN_WAIT = range(5)

CARRIERS = ["jazz", "telemost", "wbstream"]

TRANSPORTS = {
    "datachannel": {"label": "datachannel (по умолчанию)", "opts": {}},
    "vp8channel": {
        "label": "vp8channel",
        "opts": {"vp8-fps": "60", "vp8-batch": "64"},
    },
    "seichannel": {
        "label": "seichannel",
        "opts": {"fps": "60", "batch": "64", "frag": "900", "ack-ms": "2000"},
    },
    "videochannel": {
        "label": "videochannel",
        "opts": {
            "video-codec": "qrcode", "video-w": "1080", "video-h": "1080",
            "video-fps": "60", "video-bitrate": "5000k", "video-hw": "none",
        },
    },
}

# ----- Новый конфиг -----

async def new_config_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton(c, callback_data=c)] for c in CARRIERS]
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="menu")])
    await query.edit_message_text(
        "Выбери carrier:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_CARRIER

async def new_config_carrier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    carrier = query.data
    context.user_data["carrier"] = carrier
    await query.edit_message_text(
        f"Carrier: *{carrier}*\n\nДля кого конфиг? (введи имя: Паша, Дима, ...)",
        parse_mode="Markdown"
    )
    return ASK_NAME

async def new_config_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name or len(name) > 30:
        await update.message.reply_text("Введи нормальное имя (до 30 символов):")
        return ASK_NAME

    client_id = re.sub(r"[^a-zA-Z0-9]", "", name).lower() or name.lower()
    context.user_data["name"] = name
    context.user_data["client_id"] = client_id

    carrier = context.user_data.get("carrier", "jazz")
    keyboard = [
        [InlineKeyboardButton("📝 Ввести вручную", callback_data="manual")],
        [InlineKeyboardButton("🤖 Автогенерация", callback_data="auto")],
        [InlineKeyboardButton("❌ Отмена", callback_data="menu")],
    ]
    await update.message.reply_text(
        f"Имя: *{name}*\nCarrier: *{carrier}*\n\nКак задать комнату?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_ROOM

async def new_config_room_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "manual":
        await query.edit_message_text(
            "Введи ID комнаты (например: `ipx3ff:8ks21rcn` или `ipx3ff`):",
            parse_mode="Markdown"
        )
        return ASK_ROOM

    # Автогенерация
    carrier = context.user_data.get("carrier", "jazz")
    client_id = context.user_data.get("client_id", "unknown")

    await query.edit_message_text("⏳ Генерирую ключ...")

    try:
        key_hex = await gen_key()
    except Exception as e:
        await query.edit_message_text(f"Ошибка генерации ключа: {e}")
        return ConversationHandler.END

    context.user_data["key_hex"] = key_hex
    await query.edit_message_text(f"⏳ Создаю комнату ({carrier})...")

    try:
        room_result = await gen_room(client_id, key_hex, carrier)
    except Exception as e:
        await query.edit_message_text(f"Ошибка создания комнаты: {e}")
        return ConversationHandler.END

    room_id = room_result.get("room_id")
    if not room_id:
        raw = room_result.get("raw", "нет")[:300]
        await query.edit_message_text(
            f"Не удалось создать комнату.\nВывод: {raw}\n\nПопробуй ввести ID вручную:",
            reply_markup=None
        )
        return ASK_ROOM

    await _finish_config(update, context, room_id)
    return ASK_TRANSPORT

async def new_config_room_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    room_id = update.message.text.strip()
    if not room_id:
        await update.message.reply_text("Введи ID комнаты:")
        return ASK_ROOM

    context.user_data["room_id"] = room_id
    return await _ask_transport(update, context)


async def _ask_transport(update, context):
    """Показать выбор транспорта."""
    keyboard = []
    for key, info in TRANSPORTS.items():
        keyboard.append([InlineKeyboardButton(info["label"], callback_data=key)])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="menu")])

    text = "Выбери транспорт:"
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ASK_TRANSPORT


async def new_config_transport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    transport = query.data

    if transport not in TRANSPORTS:
        await query.edit_message_text("Неверный транспорт.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    context.user_data["transport"] = transport
    context.user_data["transport_opts"] = TRANSPORTS[transport]["opts"]

    # Генерируем ключ если ещё нет (для manual flow)
    if "key_hex" not in context.user_data:
        await query.edit_message_text("⏳ Генерирую ключ...")
        try:
            key_hex = await gen_key()
            context.user_data["key_hex"] = key_hex
        except Exception as e:
            await query.edit_message_text(f"Ошибка генерации ключа: {e}")
            return ConversationHandler.END

    return await _finish_config(update, context, context.user_data.get("room_id", "any"))

async def _finish_config(update, context, room_id, msg=None):
    """Общий финишер для ручного и авто режимов."""
    name = context.user_data.get("name", "?")
    client_id = context.user_data.get("client_id", "?")
    key_hex = context.user_data.get("key_hex", "?")
    carrier = context.user_data.get("carrier", "jazz")
    transport = context.user_data.get("transport", "datachannel")

    await create_profile(name, client_id, key_hex, room_id, carrier, transport)

    text = (
        f"✅ Конфиг для *{name}*\n\n"
        f"Ключ:\n`{key_hex}`\n\n"
        f"Комната:\n`{room_id}`\n\n"
        f"Client ID:\n`{client_id}`\n\n"
        f"Carrier: `{carrier}`\n"
        f"Transport: `{transport}`"
    )

    if msg:
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=main_menu_keyboard())
    else:
        query = update.callback_query
        if query:
            await query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                text, parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )

async def new_config_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Отменено.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ----- 📋 Конфиги -----

async def list_configs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profiles = await list_profiles()
    if not profiles:
        await query.edit_message_text("Нет сохранённых конфигов.", reply_markup=main_menu_keyboard())
        return

    keyboard = []
    for p in profiles:
        label = f"{p['name']} ({p['client_id']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"{CB_DETAIL}:{p['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu")])
    await query.edit_message_text("Конфиги:", reply_markup=InlineKeyboardMarkup(keyboard))

async def detail_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profile_id = int(query.data.split(":")[1])
    p = await get_profile(profile_id)
    if not p:
        await query.edit_message_text("Конфиг не найден.", reply_markup=main_menu_keyboard())
        return

    text = (
        f"*{p['name']}*\n\n"
        f"Ключ:\n`{p['key_hex']}`\n\n"
        f"Комната:\n`{p['room_id']}`\n\n"
        f"Client ID:\n`{p['client_id']}`\n\n"
        f"Carrier: `{p['carrier']}`\nTransport: `{p['transport']}`"
    )
    keyboard = [
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"{CB_DELETE}:{profile_id}")],
        [InlineKeyboardButton("◀️ К списку", callback_data=CB_LIST)],
        [InlineKeyboardButton("🏠 Меню", callback_data="menu")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profile_id = int(query.data.split(":")[1])
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"{CB_CONFIRM_DELETE}:{profile_id}"),
            InlineKeyboardButton("❌ Нет", callback_data=CB_LIST),
        ]
    ]
    await query.edit_message_text("Точно удалить?", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profile_id = int(query.data.split(":")[1])
    await delete_profile(profile_id)
    await query.edit_message_text("Удалено.", reply_markup=main_menu_keyboard())

# ----- ▶️ Запустить / ⏹ Остановить -----

async def start_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profiles = await list_profiles()
    if not profiles:
        await query.edit_message_text("Нет конфигов для запуска.", reply_markup=main_menu_keyboard())
        return

    keyboard = []
    for p in profiles:
        label = f"{p['name']} ({p['client_id']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"do_start:{p['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu")])
    await query.edit_message_text("Кого запустить?", reply_markup=InlineKeyboardMarkup(keyboard))

async def do_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profile_id = int(query.data.split(":")[1])
    p = await get_profile(profile_id)
    if not p:
        await query.edit_message_text("Конфиг не найден.", reply_markup=main_menu_keyboard())
        return

    service_name = f"olcrtc-{p['client_id']}"

    # Всегда пересоздаём юнит (БД может быть новее файла)
    unit_path = f"/etc/systemd/system/{service_name}.service"
    await query.edit_message_text(f"⏳ Обновляю сервис `{service_name}`...", parse_mode="Markdown")
    created, msg = await create_service(p)
    if not created:
        await query.edit_message_text(
            f"❌ Ошибка обновления сервиса:\n{msg[:300]}",
            reply_markup=main_menu_keyboard(),
        )
        return

    await query.edit_message_text(f"⏳ Запускаю `{service_name}`...", parse_mode="Markdown")

    ok, output = await systemctl("start", service_name)
    if ok:
        await set_profile_active(profile_id, True)
        await query.edit_message_text(
            f"✅ Сервис `{service_name}` запущен.", parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.edit_message_text(
            f"❌ Ошибка запуска `{service_name}`:\n{output[:300]}",
            reply_markup=main_menu_keyboard(),
        )

async def stop_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profiles = await list_profiles()
    active = [p for p in profiles if p.get("active")]
    if not active:
        await query.edit_message_text("Нет активных сервисов.", reply_markup=main_menu_keyboard())
        return

    keyboard = []
    for p in profiles:
        label = f"{p['name']} ({p['client_id']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"do_stop:{p['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="menu")])
    await query.edit_message_text("Кого остановить?", reply_markup=InlineKeyboardMarkup(keyboard))

async def do_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profile_id = int(query.data.split(":")[1])
    p = await get_profile(profile_id)
    if not p:
        await query.edit_message_text("Конфиг не найден.", reply_markup=main_menu_keyboard())
        return

    service_name = f"olcrtc-{p['client_id']}"
    await query.edit_message_text(f"⏳ Останавливаю `{service_name}`...", parse_mode="Markdown")

    ok, output = await systemctl("stop", service_name)
    if ok:
        await set_profile_active(profile_id, False)
        await query.edit_message_text(
            f"✅ Сервис `{service_name}` остановлен.", parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.edit_message_text(
            f"❌ Ошибка остановки `{service_name}`:\n{output[:300]}",
            reply_markup=main_menu_keyboard(),
        )

# ----- 🔄 Статус -----

async def status_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    profiles = await list_profiles()
    if not profiles:
        await query.edit_message_text("Нет конфигов.", reply_markup=main_menu_keyboard())
        return

    lines = ["*Статус сервисов:*\n"]
    for p in profiles:
        service_name = f"olcrtc-{p['client_id']}"
        ok, output = await systemctl("is-active", service_name)
        status = output.strip() if ok else "inactive"
        emoji = "🟢" if status == "active" else "🔴"
        lines.append(f"{emoji} *{p['name']}* ({service_name}): `{status}`")

        # Добавляем последние 3 строки логов если active
        if status == "active":
            logs = await journalctl(service_name, 3)
            if logs and logs != "-- No entries --":
                for log_line in logs.strip().split("\n")[-2:]:
                    lines.append(f"  _{log_line.strip()[:120]}_")

    text = "\n".join(lines)
    keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ----- Main menu callback -----

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await back_to_menu(update, context)

# ----- Build app -----

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # /start
    app.add_handler(CommandHandler("start", start))

    # Новый конфиг flow
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(new_config_start, pattern=f"^{CB_NEW}$")],
        states={
            ASK_CARRIER: [
                CallbackQueryHandler(new_config_carrier, pattern="^(jazz|telemost|wbstream)$"),
            ],
            ASK_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_config_name),
            ],
            ASK_ROOM: [
                CallbackQueryHandler(new_config_room_choice, pattern="^(manual|auto)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, new_config_room_manual),
            ],
            ASK_TRANSPORT: [
                CallbackQueryHandler(new_config_transport, pattern="^(datachannel|vp8channel|seichannel|videochannel)$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(new_config_cancel, pattern="^menu$")],
    )
    app.add_handler(conv_handler)

    # Список конфигов
    app.add_handler(CallbackQueryHandler(list_configs, pattern=f"^{CB_LIST}$"))
    app.add_handler(CallbackQueryHandler(detail_config, pattern=f"^{CB_DETAIL}:\\d+$"))
    app.add_handler(CallbackQueryHandler(delete_confirm, pattern=f"^{CB_DELETE}:\\d+$"))
    app.add_handler(CallbackQueryHandler(delete_execute, pattern=f"^{CB_CONFIRM_DELETE}:\\d+$"))

    # Запуск
    app.add_handler(CallbackQueryHandler(start_service, pattern=f"^{CB_START}$"))
    app.add_handler(CallbackQueryHandler(do_start, pattern=r"^do_start:\d+$"))

    # Остановка
    app.add_handler(CallbackQueryHandler(stop_service, pattern=f"^{CB_STOP}$"))
    app.add_handler(CallbackQueryHandler(do_stop, pattern=r"^do_stop:\d+$"))

    # Статус
    app.add_handler(CallbackQueryHandler(status_all, pattern=f"^{CB_STATUS}$"))

    # Меню
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
