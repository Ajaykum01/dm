import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest, RetryAfter

from database import get_all_user_ids

logger = logging.getLogger(__name__)

# ==============================
# CONFIG
# ==============================
OWNER_ID = 7758558590
SLEEP_TIME = 0.09
PROGRESS_EVERY = 25

# ==============================
# GLOBAL STATE (ASYNCIO)
# ==============================
broadcast_task: asyncio.Task | None = None


# ==============================
# COMMAND
# ==============================
async def broad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global broadcast_task

    if update.effective_user.id != OWNER_ID:
        return

    if broadcast_task and not broadcast_task.done():
        await update.message.reply_text("⚠️ A broadcast is already running.")
        return

    message = None
    if context.args:
        message = " ".join(context.args)
    elif update.message.reply_to_message:
        message = update.message.reply_to_message

    if not message:
        await update.message.reply_text(
            "❌ Usage:\n"
            "/broad <message>\n"
            "OR reply to a message with /broad"
        )
        return

    user_ids = get_all_user_ids()
    if not user_ids:
        await update.message.reply_text("⚠️ No users found.")
        return

    status_msg = await update.message.reply_text(
        f"📣 Broadcast started\n\n"
        f"👥 Total users: {len(user_ids)}\n"
        f"📨 Sent: 0\n"
        f"🚫 Blocked: 0\n"
        f"⚠️ Errors: 0"
    )

    # 🔥 ASYNCIO BACKGROUND TASK (DETACHED)
    broadcast_task = asyncio.create_task(
        broadcast_worker(
            bot=context.bot,
            status_msg=status_msg,
            user_ids=user_ids,
            message=message
        )
    )

    # return immediately → no blocking
    return


# ==============================
# BACKGROUND WORKER
# ==============================
async def broadcast_worker(bot, status_msg, user_ids, message):
    sent = blocked = errors = 0
    total = len(user_ids)
    last_update = 0

    for index, user_id in enumerate(user_ids, start=1):
        try:
            if isinstance(message, str):
                await bot.send_message(chat_id=user_id, text=message)
            else:
                await message.copy(chat_id=user_id)

            sent += 1

        except Forbidden:
            blocked += 1
        except BadRequest:
            errors += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            continue
        except Exception as e:
            logger.warning(f"Broadcast error {user_id}: {e}")
            errors += 1

        # yield control to event loop
        await asyncio.sleep(SLEEP_TIME)

        # throttled progress update
        if index - last_update >= PROGRESS_EVERY or index == total:
            last_update = index
            try:
                await status_msg.edit_text(
                    f"📣 Broadcasting...\n\n"
                    f"👥 Total: {total}\n"
                    f"📨 Sent: {sent}\n"
                    f"🚫 Blocked: {blocked}\n"
                    f"⚠️ Errors: {errors}\n\n"
                    f"📊 Progress: {index}/{total}"
                )
            except Exception:
                pass

    try:
        await status_msg.edit_text(
            f"✅ Broadcast completed\n\n"
            f"👥 Total: {total}\n"
            f"📨 Sent: {sent}\n"
            f"🚫 Blocked: {blocked}\n"
            f"⚠️ Errors: {errors}"
        )
    except Exception:
        pass
