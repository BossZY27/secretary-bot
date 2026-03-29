import os
import logging
import asyncio
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import database as db
import gemini_brain as brain
import notifier

# Load environment variables
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Track which users have active notification loops
active_notify_users = set()


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def format_schedule(s: dict) -> str:
    """Format a single schedule for display."""
    return f"📌 {s['title']}\n   📅 {s['date']} ⏰ {s['start_time']}-{s['end_time']}" + (
        f"\n   📝 {s['notes']}" if s.get('notes') else ""
    )


def format_schedule_list(schedules: list[dict]) -> str:
    """Format a list of schedules for display."""
    if not schedules:
        return "ไม่มีตารางงาน"
    return "\n\n".join(format_schedule(s) for s in schedules)


def ensure_notification_loop(bot, user_id: int):
    """Start notification loop for a user if not already running."""
    if user_id not in active_notify_users:
        if db.is_notify_enabled(user_id):
            active_notify_users.add(user_id)
            asyncio.create_task(notifier.notification_loop(bot, user_id))
            logger.info(f"Started notification loop for user {user_id}")


# --- Handlers ---

async def start_handler(update: Update, context):
    user_id = update.effective_user.id

    await update.message.reply_text(
        "สวัสดีค่ะ! 👋 ฉันคือ น้องเลขา บอทเลขาส่วนตัวของคุณ\n\n"
        "สิ่งที่ฉันทำได้:\n"
        "💬 พิมพ์บอกนัดหมาย เช่น \"ประชุมพรุ่งนี้ 10 โมง\"\n"
        "📷 ส่งรูปตารางงาน/ตารางเรียนให้อ่าน\n"
        "🕐 ถามเวลาว่าง เช่น \"วันนี้ว่างตอนไหน\"\n"
        "📋 /list - ดูตารางงานทั้งหมด\n"
        "🗑 /delete - ลบตารางงาน\n"
        "🔔 /notify - เปิด/ปิดแจ้งเตือนอัตโนมัติ\n\n"
        "ลองพิมพ์อะไรมาได้เลยค่ะ!"
    )

    # Auto-enable notifications on first use
    if not db.is_notify_enabled(user_id):
        db.set_notify_enabled(user_id, True)
        ensure_notification_loop(context.bot, user_id)
        await update.message.reply_text(
            "🔔 เปิดแจ้งเตือนอัตโนมัติให้แล้วค่ะ!\n"
            "☀️ สรุปตารางทุกเช้า 7:00\n"
            "⏰ แจ้งเตือน 15 นาทีก่อนนัด\n\n"
            "พิมพ์ /notify เพื่อปิด/เปิดได้ค่ะ"
        )


async def notify_handler(update: Update, context):
    """Toggle notification on/off."""
    user_id = update.effective_user.id
    currently_enabled = db.is_notify_enabled(user_id)

    if currently_enabled:
        db.set_notify_enabled(user_id, False)
        active_notify_users.discard(user_id)
        await update.message.reply_text(
            "🔕 ปิดแจ้งเตือนแล้วค่ะ\n"
            "พิมพ์ /notify อีกครั้งเพื่อเปิดใหม่ได้ค่ะ"
        )
    else:
        db.set_notify_enabled(user_id, True)
        ensure_notification_loop(context.bot, user_id)
        await update.message.reply_text(
            "🔔 เปิดแจ้งเตือนแล้วค่ะ!\n"
            "☀️ สรุปตารางทุกเช้า 7:00\n"
            "⏰ แจ้งเตือน 15 นาทีก่อนนัด"
        )


async def list_handler(update: Update, context):
    user_id = update.effective_user.id
    schedules = db.get_schedules(user_id)

    if not schedules:
        await update.message.reply_text("ยังไม่มีตารางงานค่ะ ลองพิมพ์บอกหรือส่งรูปมาได้เลย!")
        return

    text = "📋 ตารางงานทั้งหมด:\n\n" + format_schedule_list(schedules)
    await update.message.reply_text(text)


async def delete_handler(update: Update, context):
    user_id = update.effective_user.id
    schedules = db.get_schedules(user_id)

    if not schedules:
        await update.message.reply_text("ไม่มีตารางงานให้ลบค่ะ")
        return

    # Show schedules with delete buttons
    keyboard = []
    for s in schedules:
        btn_text = f"❌ {s['date']} {s['start_time']} {s['title']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_{s['id']}")])

    keyboard.append([InlineKeyboardButton("🗑 ลบทั้งหมด", callback_data="del_all")])
    keyboard.append([InlineKeyboardButton("↩️ ยกเลิก", callback_data="cancel")])

    await update.message.reply_text(
        "เลือกรายการที่ต้องการลบ:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def text_handler(update: Update, context):
    user_id = update.effective_user.id
    message = update.message.text

    # Ensure notification loop is running
    ensure_notification_loop(context.bot, user_id)

    # Show typing indicator
    await update.message.chat.send_action("typing")

    # Classify intent
    intent = await brain.classify_intent(message)
    logger.info(f"User {user_id} intent: {intent} | message: {message}")

    if intent == "add":
        await handle_add(update, context, message)
    elif intent == "query_free":
        await handle_query_free(update, context, message)
    elif intent == "list":
        await list_handler(update, context)
    elif intent == "delete":
        await handle_delete_by_text(update, context, message)
    else:
        await handle_chat(update, context, message)


async def handle_add(update: Update, context, message: str):
    user_id = update.effective_user.id

    schedules = await brain.parse_text_to_schedules(message, today_str())

    if not schedules:
        await update.message.reply_text("ขอโทษค่ะ ไม่เข้าใจข้อมูลตารางงาน ลองพิมพ์ใหม่อีกครั้งนะคะ")
        return

    # Store parsed schedules temporarily
    context.user_data["pending_schedules"] = schedules

    # Show parsed result for confirmation
    text = "📝 ฉันเข้าใจว่าคุณต้องการเพิ่ม:\n\n"
    text += format_schedule_list(schedules)
    text += "\n\nถูกต้องไหมคะ?"

    keyboard = [
        [
            InlineKeyboardButton("✅ ถูกต้อง บันทึกเลย", callback_data="confirm_add"),
            InlineKeyboardButton("❌ ยกเลิก", callback_data="cancel"),
        ]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_query_free(update: Update, context, message: str):
    user_id = update.effective_user.id

    # Get schedules for this week and next week
    today = datetime.now()
    end_date = today + timedelta(days=14)
    schedules = db.get_schedules_range(user_id, today.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

    response = await brain.analyze_free_time(message, schedules, today_str())
    await update.message.reply_text(response)


async def handle_delete_by_text(update: Update, context, message: str):
    user_id = update.effective_user.id
    schedules = db.get_schedules(user_id)

    if not schedules:
        await update.message.reply_text("ไม่มีตารางงานให้ลบค่ะ")
        return

    ids_to_delete = await brain.parse_delete_request(message, schedules, today_str())

    if not ids_to_delete:
        # Fall back to showing delete buttons
        await delete_handler(update, context)
        return

    # Store for confirmation
    context.user_data["pending_delete_ids"] = ids_to_delete
    to_delete = [s for s in schedules if s["id"] in ids_to_delete]

    text = "🗑 ต้องการลบรายการนี้ใช่ไหมคะ?\n\n"
    text += format_schedule_list(to_delete)

    keyboard = [
        [
            InlineKeyboardButton("✅ ลบเลย", callback_data="confirm_delete"),
            InlineKeyboardButton("❌ ยกเลิก", callback_data="cancel"),
        ]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_chat(update: Update, context, message: str):
    user_id = update.effective_user.id
    today = datetime.now()
    end_date = today + timedelta(days=7)
    schedules = db.get_schedules_range(user_id, today.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))

    response = await brain.chat_response(message, schedules, today_str())
    await update.message.reply_text(response)


async def photo_handler(update: Update, context):
    user_id = update.effective_user.id

    # Ensure notification loop is running
    ensure_notification_loop(context.bot, user_id)

    await update.message.chat.send_action("typing")
    await update.message.reply_text("📷 กำลังอ่านรูปภาพ... รอสักครู่นะคะ")

    # Download the photo (highest resolution)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    # Parse image with Gemini
    schedules = await brain.parse_image_to_schedules(bytes(image_bytes), today_str())

    if not schedules:
        await update.message.reply_text(
            "ขอโทษค่ะ อ่านรูปไม่ออก หรือไม่พบตารางงานในรูป\n"
            "ลองส่งรูปที่ชัดกว่านี้ หรือพิมพ์บอกได้เลยค่ะ"
        )
        return

    # Store for confirmation
    context.user_data["pending_schedules"] = schedules

    text = f"📷 อ่านได้ {len(schedules)} รายการ:\n\n"
    text += format_schedule_list(schedules)
    text += "\n\nต้องการบันทึกไหมคะ?"

    keyboard = [
        [
            InlineKeyboardButton("✅ บันทึกทั้งหมด", callback_data="confirm_add"),
            InlineKeyboardButton("❌ ยกเลิก", callback_data="cancel"),
        ]
    ]

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def callback_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "confirm_add":
        schedules = context.user_data.get("pending_schedules", [])
        if schedules:
            count = db.add_schedules_bulk(user_id, schedules)
            await query.edit_message_text(f"✅ บันทึกแล้ว {count} รายการค่ะ!")
            context.user_data.pop("pending_schedules", None)
        else:
            await query.edit_message_text("ไม่มีข้อมูลให้บันทึกค่ะ")

    elif data == "confirm_delete":
        ids = context.user_data.get("pending_delete_ids", [])
        deleted = 0
        for sid in ids:
            if db.delete_schedule(user_id, sid):
                deleted += 1
        await query.edit_message_text(f"🗑 ลบแล้ว {deleted} รายการค่ะ!")
        context.user_data.pop("pending_delete_ids", None)

    elif data.startswith("del_"):
        if data == "del_all":
            schedules = db.get_schedules(user_id)
            for s in schedules:
                db.delete_schedule(user_id, s["id"])
            await query.edit_message_text(f"🗑 ลบทั้งหมดแล้วค่ะ ({len(schedules)} รายการ)")
        else:
            schedule_id = int(data.split("_")[1])
            if db.delete_schedule(user_id, schedule_id):
                await query.edit_message_text("🗑 ลบแล้วค่ะ!")
            else:
                await query.edit_message_text("ไม่พบรายการนี้ค่ะ")

    elif data == "cancel":
        context.user_data.pop("pending_schedules", None)
        context.user_data.pop("pending_delete_ids", None)
        await query.edit_message_text("ยกเลิกแล้วค่ะ ✨")


async def error_handler(update: Update, context):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "ขอโทษค่ะ เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้งนะคะ 🙏"
        )


def main():
    # Initialize database
    db.init_db()

    # Build bot
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: กรุณาตั้งค่า TELEGRAM_BOT_TOKEN ในไฟล์ .env")
        return

    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("delete", delete_handler))
    app.add_handler(CommandHandler("notify", notify_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)

    # Start notification loops for all users with notifications enabled
    async def post_init(application):
        user_ids = db.get_notify_enabled_users()
        for user_id in user_ids:
            active_notify_users.add(user_id)
            asyncio.create_task(notifier.notification_loop(application.bot, user_id))
            logger.info(f"Started notification loop for user {user_id}")

    app.post_init = post_init

    print("🤖 น้องเลขา พร้อมทำงานแล้วค่ะ!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
