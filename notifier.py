import logging
import asyncio
from datetime import datetime

import database as db

logger = logging.getLogger(__name__)


def format_schedule_notify(s: dict) -> str:
    return f"  📌 {s['title']} ({s['start_time']}-{s['end_time']})" + (
        f" - {s['notes']}" if s.get('notes') else ""
    )


async def send_morning_summary(bot, user_id: int):
    """Send daily morning summary of today's schedules via Telegram."""
    today = datetime.now().strftime("%Y-%m-%d")
    schedules = db.get_schedules(user_id, date=today)

    if schedules:
        msg = f"☀️ สวัสดีตอนเช้าค่ะ! ตารางวันนี้ ({today}):\n\n"
        for s in schedules:
            msg += format_schedule_notify(s) + "\n"
        msg += f"\nมีทั้งหมด {len(schedules)} รายการค่ะ"
    else:
        msg = f"☀️ สวัสดีตอนเช้าค่ะ! วันนี้ ({today}) ไม่มีนัดหมาย ว่างทั้งวันเลยค่ะ ✨"

    try:
        await bot.send_message(chat_id=user_id, text=msg)
        logger.info(f"Morning summary sent to user {user_id}")
    except Exception as e:
        logger.error(f"Failed to send morning summary to {user_id}: {e}")


async def check_upcoming_events(bot, user_id: int, minutes_before: int = 15):
    """Check for events happening soon and send reminders via Telegram."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    schedules = db.get_schedules(user_id, date=today)

    for s in schedules:
        try:
            event_time = datetime.strptime(f"{s['date']} {s['start_time']}", "%Y-%m-%d %H:%M")
            diff = (event_time - now).total_seconds() / 60

            # Send reminder if event is within the reminder window
            if minutes_before - 1 <= diff <= minutes_before + 1:
                msg = (
                    f"⏰ แจ้งเตือน! อีก {minutes_before} นาทีจะถึงเวลา:\n\n"
                    f"  📌 {s['title']}\n"
                    f"  🕐 {s['start_time']}-{s['end_time']}"
                )
                if s.get('notes'):
                    msg += f"\n  📝 {s['notes']}"

                await bot.send_message(chat_id=user_id, text=msg)
                logger.info(f"Reminder sent for: {s['title']} at {s['start_time']}")
        except ValueError:
            continue


async def notification_loop(bot, user_id: int, morning_hour: int = 7):
    """Background loop that checks for reminders every minute."""
    logger.info(f"Notification loop started for user {user_id}")
    last_morning_date = None

    while True:
        now = datetime.now()

        try:
            # Morning summary: send once per day at the specified hour
            if now.hour == morning_hour and now.minute == 0:
                today = now.strftime("%Y-%m-%d")
                if last_morning_date != today:
                    await send_morning_summary(bot, user_id)
                    last_morning_date = today

            # Check upcoming events every minute
            await check_upcoming_events(bot, user_id, minutes_before=15)

        except Exception as e:
            logger.error(f"Notification error for user {user_id}: {e}")

        # Wait 1 minute before next check
        await asyncio.sleep(60)
