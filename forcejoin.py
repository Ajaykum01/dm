"""
Force Join Module
Enforces users to join specified group and channel before using bot commands.
"""

from functools import wraps
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Configuration ---
GROUP_ID = -1003838614236
CHANNEL_ID = -1003074006773

# 🔥 Direct links (NO username confusion)
GROUP_LINK = "https://t.me/aurachkgtpup"
CHANNEL_LINK = "https://t.me/+E6zoRhIFhtNmM2E5"

FORCE_JOIN_IMAGE = "https://i.ibb.co/9kQbF5T3/5028670151544474400.jpg"

# Logger
logger = logging.getLogger("force_join")
logger.setLevel(logging.INFO)


# --- Helper: Safe membership check ---
async def safe_get_member(bot, chat_id: int, user_id: int):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        logger.info(f"[DEBUG] User {user_id} in {chat_id}: {member.status}")
        return member.status
    except Exception as e:
        logger.warning(
            f"[SAFE CHECK] Failed to get member {user_id} in {chat_id}: {e}"
        )
        return None


async def is_user_joined(bot, user_id: int) -> bool:
    valid_statuses = ("member", "administrator", "creator")

    group_status = await safe_get_member(bot, GROUP_ID, user_id)
    if group_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in group ({group_status})")
        return False

    channel_status = await safe_get_member(bot, CHANNEL_ID, user_id)
    if channel_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in channel ({channel_status})")
        return False

    logger.info(f"User {user_id} is in group & channel ✅")
    return True


# --- Force Join Decorator ---
def force_join(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):

        if not update.effective_user:
            return

        user_id = update.effective_user.id

        if update.message and update.message.text:
            if update.message.text.startswith("/start"):
                return await func(update, context, *args, **kwargs)

        joined = await is_user_joined(context.bot, user_id)
        if not joined:

            keyboard = [
                [InlineKeyboardButton("📢 Join Group", url=GROUP_LINK)],
                [InlineKeyboardButton("📡 Join Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            caption_text = (
                "❌ 𝗨𝗻𝗹𝗼𝗰𝗸 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗼 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗯𝘆 𝗷𝗼𝗶𝗻𝗶𝗻𝗴 "
                "𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽 👇\n\n"
                "🔒 𝗔𝗹𝗹 𝗳𝗲𝗮𝘁𝘂𝗿𝗲𝘀 𝗮𝗿𝗲 𝗿𝗲𝘀𝘁𝗿𝗶𝗰𝘁𝗲𝗱.\n"
                "✅ 𝗝𝗼𝗶𝗻 𝗯𝗼𝘁𝗵 𝘁𝗼 𝘂𝗻𝗹𝗼𝗰𝗸."
            )

            if update.message:
                target = update.message
            elif update.callback_query and update.callback_query.message:
                target = update.callback_query.message
            else:
                return

            await target.reply_photo(
                photo=FORCE_JOIN_IMAGE,
                caption=caption_text,
                reply_markup=reply_markup
            )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


# --- Callback Handler ---
async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query or not query.from_user:
        return

    user_id = query.from_user.id
    logger.info(f"Callback triggered by user {user_id}")

    joined = await is_user_joined(context.bot, user_id)

    if joined:
        await query.answer(
            "✅ Access granted! You can now use the bot.",
            show_alert=True
        )
        try:
            await query.edit_message_caption(
                "✨ 𝗪𝗲𝗹𝗰𝗼𝗺𝗲!\n\n"
                "🎉 You have successfully joined the group & channel.\n"
                "🚀 Enjoy using the bot!"
            )
        except Exception:
            pass
    else:
        await query.answer(
            "❌ You still need to join both!",
            show_alert=True
        )


__all__ = [
    "force_join",
    "check_joined_callback",
    "GROUP_ID",
    "CHANNEL_ID",
    "FORCE_JOIN_IMAGE"
    ]
return False

    channel_status = await safe_get_member(bot, CHANNEL_ID, user_id)
    if channel_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in channel ({channel_status})")
        return False

    logger.info(f"User {user_id} is in group & channel ✅")
    return True


# --- Force Join Decorator ---
def force_join(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):

        if not update.effective_user:
            return

        user_id = update.effective_user.id

        if update.message and update.message.text:
            if update.message.text.startswith("/start"):
                return await func(update, context, *args, **kwargs)

        joined = await is_user_joined(context.bot, user_id)
        if not joined:

            keyboard = [
                [InlineKeyboardButton("📢 Join Group", url=GROUP_LINK)],
                [InlineKeyboardButton("📡 Join Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            caption_text = (
                "❌ 𝗨𝗻𝗹𝗼𝗰𝗸 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗼 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗯𝘆 𝗷𝗼𝗶𝗻𝗶𝗻𝗴 "
                "𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽 👇\n\n"
                "🔒 𝗔𝗹𝗹 𝗳𝗲𝗮𝘁𝘂𝗿𝗲𝘀 𝗮𝗿𝗲 𝗿𝗲𝘀𝘁𝗿𝗶𝗰𝘁𝗲𝗱.\n"
                "✅ 𝗝𝗼𝗶𝗻 𝗯𝗼𝘁𝗵 𝘁𝗼 𝘂𝗻𝗹𝗼𝗰𝗸."
            )

            if update.message:
                target = update.message
            elif update.callback_query and update.callback_query.message:
                target = update.callback_query.message
            else:
                return

            await target.reply_photo(
                photo=FORCE_JOIN_IMAGE,
                caption=caption_text,
                reply_markup=reply_markup
            )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


# --- Callback Handler ---
def check_joined_callback(update, context):
    if not query or not query.from_user:
        return

    user_id = query.from_user.id
    logger.info(f"Callback triggered by user {user_id}")

    async def check_joined_callback(update, context):
        if joined:
        await query.answer(
            "✅ Access granted! You can now use the bot.",
            show_alert=True
        )
        try:
            await query.edit_message_caption(
"""
Force Join Module
Enforces users to join specified group and channel before using bot commands.
"""

from functools import wraps
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# --- Configuration ---
GROUP_ID = -1003838614236
CHANNEL_ID = -1003074006773

# 🔥 Direct links (NO username confusion)
GROUP_LINK = "https://t.me/aurachkgtpup"
CHANNEL_LINK = "https://t.me/+E6zoRhIFhtNmM2E5"

FORCE_JOIN_IMAGE = "https://i.ibb.co/9kQbF5T3/5028670151544474400.jpg"

# Logger
logger = logging.getLogger("force_join")
logger.setLevel(logging.INFO)


# --- Helper: Safe membership check ---
async def safe_get_member(bot, chat_id: int, user_id: int):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        logger.info(f"[DEBUG] User {user_id} in {chat_id}: {member.status}")
        return member.status
    except Exception as e:
        logger.warning(
            f"[SAFE CHECK] Failed to get member {user_id} in {chat_id}: {e}"
        )
        return None


async def is_user_joined(bot, user_id: int) -> bool:
    valid_statuses = ("member", "administrator", "creator")

    group_status = await safe_get_member(bot, GROUP_ID, user_id)
    if group_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in group ({group_status})")
        return False

    channel_status = await safe_get_member(bot, CHANNEL_ID, user_id)
    if channel_status not in valid_statuses:
        logger.warning(f"User {user_id} NOT in channel ({channel_status})")
        return False

    logger.info(f"User {user_id} is in group & channel ✅")
    return True


# --- Force Join Decorator ---
def force_join(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):

        if not update.effective_user:
            return

        user_id = update.effective_user.id

        if update.message and update.message.text:
            if update.message.text.startswith("/start"):
                return await func(update, context, *args, **kwargs)

        joined = await is_user_joined(context.bot, user_id)
        if not joined:

            keyboard = [
                [InlineKeyboardButton("📢 Join Group", url=GROUP_LINK)],
                [InlineKeyboardButton("📡 Join Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("✅ I have joined", callback_data="check_joined")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            caption_text = (
                "❌ 𝗨𝗻𝗹𝗼𝗰𝗸 𝗮𝗰𝗰𝗲𝘀𝘀 𝘁𝗼 𝘁𝗵𝗲 𝗯𝗼𝘁 𝗯𝘆 𝗷𝗼𝗶𝗻𝗶𝗻𝗴 "
                "𝗼𝘂𝗿 𝗰𝗵𝗮𝗻𝗻𝗲𝗹 𝗮𝗻𝗱 𝗴𝗿𝗼𝘂𝗽 👇\n\n"
                "🔒 𝗔𝗹𝗹 𝗳𝗲𝗮𝘁𝘂𝗿𝗲𝘀 𝗮𝗿𝗲 𝗿𝗲𝘀𝘁𝗿𝗶𝗰𝘁𝗲𝗱.\n"
                "✅ 𝗝𝗼𝗶𝗻 𝗯𝗼𝘁𝗵 𝘁𝗼 𝘂𝗻𝗹𝗼𝗰𝗸."
            )

            if update.message:
                target = update.message
            elif update.callback_query and update.callback_query.message:
                target = update.callback_query.message
            else:
                return

            await target.reply_photo(
                photo=FORCE_JOIN_IMAGE,
                caption=caption_text,
                reply_markup=reply_markup
            )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


# --- Callback Handler ---
async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query or not query.from_user:
        return

    user_id = query.from_user.id
    logger.info(f"Callback triggered by user {user_id}")

    joined = await is_user_joined(context.bot, user_id)

    if joined:
        await query.answer(
            "✅ Access granted! You can now use the bot.",
            show_alert=True
        )
        try:
            await query.edit_message_caption(
                "✨ 𝗪𝗲𝗹𝗰𝗼𝗺𝗲!\n\n"
                "🎉 You have successfully joined the group & channel.\n"
                "🚀 Enjoy using the bot!"
            )
        except Exception:
            pass
    else:
        await query.answer(
            "❌ You still need to join both!",
            show_alert=True
        )


__all__ = [
    "force_join",
    "check_joined_callback",
    "GROUP_ID",
    "CHANNEL_ID",
    "FORCE_JOIN_IMAGE",
]
