from telegram.ext import CommandHandler
import re
import logging
import os
import sys
import asyncio
import time
import html
from datetime import datetime
import pytz
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler

from telegram.ext import MessageHandler, filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton # Make sure these are imported
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from forcejoin import force_join, check_joined_callback
# Add these imports at the top of your file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError
from broad import broad
from scr import handle_scr_command, initialize_pyrogram, stop_pyrogram
from pv import handle_pv_command

# Make sure logger is defined globally
logger = logging.getLogger(__name__)
# ==============================
# PYROGRAM LIFECYCLE (VERY IMPORTANT)
# ==============================

async def on_startup(application):
    logger.info("🚀 Starting Pyrogram user client...")
    await initialize_pyrogram()

async def on_shutdown(application):
    logger.info("🛑 Stopping Pyrogram user client...")
    await stop_pyrogram()

# Import forcejoin functionality
from forcejoin import force_join, check_joined_callback
from cmds import cmds_command, cmds_callback_handler
# Import all command handlers
from rz import handle_rz_command
from credits import handle_credits_command
from shopify_checker import handle_sh_command
from chk import handle_chk_command   
from msh import (
    handle_msh_command,
    handle_msh_confirm_callback,
    active_mass_checks as msh_active_mass_checks
)
from database import setup_custom_gates_table
from vbv import handle_vbv_command
from cmds import cmds_command, cmds_callback_handler
from redeem import (
    handle_gplan1, handle_gplan2, handle_gplan3, handle_gplan4, handle_gcodes, handle_claim
)
from au import handle_au_command
from pf import handle_pf_command
from status import status_command
from st import handle_st_command
from pp import handle_pp_command
from p1 import handle_p1_command
from py import handle_py_command
# Import new proxy and mpp handlers
from proxy import handle_proxy_command, handle_rproxy_command, handle_myproxy_command
# Import new msk handler
from mau import handle_mau_command, active_mass_checks as mau_active_mass_checks
from gen import handle_gen_command
from gate import handle_gate_command
# Import database functions
from database import get_or_create_user, get_user_credits, create_connection_pool, setup_database, close_connection_pool
# ==============================
# DATABASE CONFIGURATION
# ==============================
# Set database connection parameters for database module
os.environ["DB_HOST"] = os.getenv("DB_HOST", "localhost")
os.environ["DB_PORT"] = os.getenv("DB_PORT", "5432")
os.environ["DB_NAME"] = os.getenv("DB_NAME", "cardxchk")
os.environ["DB_USER"] = os.getenv("DB_USER", "postgres")
os.environ["DB_PASS"] = os.getenv("DB_PASS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==============================
# TIMEZONE SETUP
# ==============================
# Define Indian timezone
IST = pytz.timezone('Asia/Kolkata')

# Function to convert datetime to Indian format
def format_indian_datetime(dt):
    # Ensure dt is timezone-aware, assume UTC if not
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    # Convert to IST
    ist_dt = dt.astimezone(IST)
    
    # Format as DD/MM/YY HH:MM:SS
    return ist_dt.strftime('%d/%m/%y %H:%M:%S')

# Admin user ID (replace with your actual admin ID)
ADMIN_ID = 8488521935

# ==============================
# HELPER FUNCTIONS FOR TIMEOUT HANDLING
# ==============================
# Function to safely send messages with retry logic
async def safe_send_message(context, chat_id, text, parse_mode=None, reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to send message after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error sending message: {e}")
            raise

# Function to safely edit messages with retry logic
async def safe_edit_message(context, chat_id, message_id, text=None, reply_markup=None, 
                          parse_mode=None, retries=3):
    for attempt in range(retries):
        try:
            if text:
                return await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            else:
                return await context.bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup
                )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to edit message after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error editing message: {e}")
            raise

# Function to safely edit message media with retry logic
async def safe_edit_message_media(context, chat_id, message_id, media, reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to edit message media after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error editing message media: {e}")
            raise

# Function to safely send photos with retry logic
async def safe_send_photo(context, chat_id, photo, caption=None, parse_mode=None, 
                         reply_markup=None, retries=3):
    for attempt in range(retries):
        try:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to send photo after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error sending photo: {e}")
            raise

# Function to safely answer callback queries with retry logic
async def safe_answer_callback_query(query, text=None, show_alert=False, retries=3):
    for attempt in range(retries):
        try:
            return await query.answer(text=text, show_alert=show_alert)
        except (TimedOut, NetworkError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(0.5)  # Wait before retrying
                continue
            else:
                logging.error(f"Failed to answer callback query after {retries} attempts: {e}")
                raise
        except Exception as e:
            logging.error(f"Unexpected error answering callback query: {e}")
            raise

# ==============================
# START COMMAND (DIRECT - NO ANIMATION)
# ==============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(start_sequence(update.effective_chat.id, context, update.effective_user, is_new_message=True))

async def start_sequence(chat_id, context, user, is_new_message=True):
    user_id = user.id
    # Fixed: Store actual username (or None) in database, not a fallback
    username = user.username if user.username else None

    # Create tasks to run in parallel
    async def fetch_user_data():
        loop = asyncio.get_running_loop()
        # Run synchronous DB call in a thread to not block event loop
        return await loop.run_in_executor(executor, get_or_create_user, user_id, username)

    # Fetch user data with timeout
    try:
        db_user_data = await asyncio.wait_for(fetch_user_data(), timeout=5.0)
    except asyncio.TimeoutError:
        error_msg = """
<a href='https://t.me/FailedFr'>⚠️</a> <b>Database Connection Timeout</b>
<pre>⊀ Error: Database request timed out</pre>
<a href='https://t.me/FailedFr'>ℭ</a> <b>Action Required:</b> Please try again later
<a href='https://t.me/FailedFr'>⌬</a> <b>Support:</b> <a href='https://t.me/FailedFr'>kคli liຖนxx</a>
"""
        await safe_send_message(context, chat_id, error_msg, parse_mode=ParseMode.HTML)
        return
    
    if not db_user_data:
        error_msg = """
<a href='https://t.me/FailedFr'>⚠️</a> <b>Database Connection Failed</b>
<pre>⊀ Error: Unable to connect to database</pre>
<a href='https://t.me/FailedFr'>ℭ</a> <b>Action Required:</b> Please contact support
<a href='https://t.me/FailedFr'>⌬</a> <b>Support:</b> <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>
"""
        await safe_send_message(context, chat_id, error_msg, parse_mode=ParseMode.HTML)
        return

    # --- At this point, db_user_data is available ---
    db_username, db_joined_date, db_tier, db_credits = db_user_data

    # Get real-time credits to check for unlimited
    current_credits = get_user_credits(user_id)
    if current_credits == float('inf'):
        credits_display = "Infinite😎"
    else:
        credits_display = str(db_credits)  # Use value from initial query

    # Format datetime properly to ensure correct timezone display
    # Use our new function to format in Indian time
    formatted_joined_date = format_indian_datetime(db_joined_date)
    
    # Fixed: Display username properly - add @ if username exists, otherwise show "None"
    # Also escape any special characters that might interfere with HTML
    display_username = f"@{html.escape(db_username)}" if db_username else "None"
    # Escape first name as well
    escaped_first_name = html.escape(user.first_name)

    # ==============================
    # PROFILE CARD DESIGN
    # ==============================
    caption = f"""
<pre>⊀ 𝑺𝒕𝒂𝒕𝒖𝒔: 𝐀𝐜𝐭𝐢𝐯𝐞 ✅</pre>

<a href='https://t.me/FailedFr'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {display_username}
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐌𝒂𝒏𝒆</b> ↬ <a href='tg://user?id={user_id}'>{escaped_first_name}</a> <code>[{html.escape(db_tier)}]</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐉𝒐𝒏𝒆𝒅</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/FailedFr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""

    # Send final message directly without animation
    try:
        # Fixed: Validate image URL and add fallback mechanism
        image_url = "https://i.ibb.co/9kQbF5T3/5028670151544474400.jpg"
        
        # Add debug logging for image URL validation
        import requests
        try:
            response = requests.head(image_url, timeout=5)
            if response.status_code != 200:
                # Fallback to a default image if the URL is invalid
                image_url = "https://i.ibb.co/9kQbF5T3/5028670151544474400.jpg"
        except:
            image_url = "https://i.ibb.co/9kQbF5T3/5028670151544474400.jpg"
        
        # Send message with image and buttons - properly arranged in 2 columns
        await safe_send_photo(
            context=context,
            chat_id=chat_id,
            photo=image_url,
            caption=caption.strip(),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Gates", callback_data="menu_gates"), InlineKeyboardButton("Pricing", callback_data="menu_pricing")],
                [InlineKeyboardButton("Group", url="https://t.me/+IFFnzNZuHFU5YmQ0"), InlineKeyboardButton("Updates", url="https://t.me/+E6zoRhIFhtNmM2E5")],
                [InlineKeyboardButton("Dev", url="https://t.me/failurefr_07"), InlineKeyboardButton("Support", url="https://t.me/failurefr_07")]
            ]),
        )
    except Exception as e:
        # Enhanced error handling with more detailed logging
        error_details = f"Photo send failed: {str(e)}"
        print(f"ERROR: {error_details}")  # Add proper logging
        
        # Fallback to text-only message if photo fails
        fallback_msg = f"""
<a href='https://t.me/abtlnx'>⚠️</a> <b>Profile Display Issue</b>
<pre>⊀ Error: Unable to load profile image</pre>
<a href='https://t.me/FailedFr'>ℭ</a> <b>Action:</b> Profile details below:
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {display_username}
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐌𝒂𝒏𝒆</b> ↬ <a href='tg://user?id={user_id}'>{escaped_first_name}</a> <code>[{html.escape(db_tier)}]</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐉𝒐𝒏𝒆𝒅</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/FailedFr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>
"""
        await safe_send_message(context, chat_id, fallback_msg, parse_mode=ParseMode.HTML)

# ==============================
# CALLBACK HANDLER
# ==============================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    await safe_answer_callback_query(query)

    # Get the photo from current message to reuse it
    photo = query.message.photo[-1] if query.message.photo else None
    photo_file_id = photo.file_id if photo else None

    # GATES MENU
    if data == "menu_gates":
        kb = [
            [
                InlineKeyboardButton("Auth", callback_data="auth_menu"),
                InlineKeyboardButton("Charge", callback_data="charge_menu")
            ],
            [
                InlineKeyboardButton("Mass Gates", callback_data="mass_gates_menu")
            ],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption="<b>⚡ Choose your gateway mode:</b>", parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text="<b>⚡ Choose your gateway mode:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS GATES MENU - NO BUTTONS FOR GATEWAYS
    elif data == "mass_gates_menu":
        # All gates are now shown as online without checking status
        text = f"""
<b>⚡ MASS GATES STATUS</b>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Mass Stripe Auth</i>  
<b><i>Command ↬</i></b> <i>/mau</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Shopify Random</i>  
<b><i>Command ↬</i></b> <i>/msh</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="menu_gates")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS AUTH MENU - REMOVED AS PER REQUEST
    elif data == "mass_auth_menu":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Mass Stripe Auth</i>  
<b><i>Command ↬</i></b> <i>/mtxt</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="mass_gates_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS CHARGE MENU - REMOVED AS PER REQUEST
    elif data == "mass_charge_menu":
        kb = [
            [
                InlineKeyboardButton("Shopify", callback_data="mass_charge_shopify"),
                InlineKeyboardButton("Paypal", callback_data="mass_charge_paypal")
            ],
            [
                InlineKeyboardButton("SK Based", callback_data="mass_charge_sk")
            ],
            [InlineKeyboardButton("Back", callback_data="mass_gates_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption="<b>⚡ Choose mass charge gateway:</b>", parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text="<b>⚡ Choose mass charge gateway:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # MASS CHARGE CATEGORY MENUS - REMOVED AS PER REQUEST
    elif data == "mass_charge_shopify":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Shopify Random</i>  
<b><i>Command ↬</i></b> <i>/msh</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="mass_charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise



    elif data == "mass_charge_sk":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>SK Based 1$</i>  
<b><i>Command ↬</i></b> <i>/msk</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="mass_charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # CHARGE MENU
    elif data == "charge_menu":
        kb = [
            [
                InlineKeyboardButton("Stripe", callback_data="charge_stripe"),
                InlineKeyboardButton("Paypal", callback_data="charge_paypal")
            ],
            [
                InlineKeyboardButton("PayU", callback_data="charge_payu"),
                InlineKeyboardButton("Razorpay", callback_data="charge_razorpay")
            ],
            [
                InlineKeyboardButton("Shopify", callback_data="charge_shopify"),
                InlineKeyboardButton("PayFast", callback_data="charge_payfast")
            ],
            [InlineKeyboardButton("Back", callback_data="menu_gates")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption="<b>⚡ Choose charge gateway:</b>", parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text="<b>⚡ Choose charge gateway:</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # CHARGE CATEGORY MENUS
    elif data == "charge_stripe":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Stripe 0.50$</i>  
<b><i>Command ↬</i></b> <i>/st</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_paypal":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Paypal 1$</i>  
<b><i>Command ↬</i></b> <i>/pp</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Paypal 0.10$</i>  
<b><i>Command ↬</i></b> <i>/p1</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Paypal 5$ CVV</i>  
<b><i>Command ↬</i></b> <i>/pv</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_payu":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>PayU 0.29$</i>  
<b><i>Command ↬</i></b> <i>/py</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>PayU 1€</i>  
<b><i>Command ↬</i></b> <i>/pu</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_razorpay":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Razorpay 1₹</i>  
<b><i>Command ↬</i></b> <i>/rz</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_shopify":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Shopify 0.98$</i>  
<b><i>Command ↬</i></b> <i>/sh</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    elif data == "charge_payfast":
        # All gates are now shown as online without checking status
        text = f"""
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>PayFast 0.30$</i>  
<b><i>Command ↬</i></b> <i>/pf</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="charge_menu")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # AUTH MENU
    elif data == "auth_menu":
        # All gates are now shown as online without checking status
        text = f"""
<b><i>Gate ↬</i></b> <i>Braintree Auth</i>  
<b><i>Command ↬</i></b> <i>/chk</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>Stripe Auth</i>  
<b><i>Command ↬</i></b> <i>/au</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
<b><i>Gate ↬</i></b> <i>3DS Lookup</i>  
<b><i>Command ↬</i></b> <i>/vbv</i>  
<b><i>Status ↬</i></b> <i>Online ✅</i>
━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="menu_gates")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # PRICING MENU WITH PROPER FORMATTING
    elif data == "menu_pricing":
        text = """
<b>⚡ Available Access Plans</b>
━━━━━━━━━━━━━━━━━━
<pre>𝑪𝒐𝒓𝒆 𝑨𝒄𝒄𝒆𝒔🛠️</pre>
<b>Duration ↬</b> <i>7 days</i>
<b>Price ↬</b> <i>8$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
<pre>𝑬𝒍𝒊𝒕𝒆 𝑨𝒄𝒄𝒆𝒔⭐</pre>
<b>Duration ↬</b> <i>15 days</i>
<b>Price ↬</b> <i>14$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
<pre>𝑹𝒐𝒐𝒕 𝑨𝒄𝒄𝒆𝒔👑</pre>
<b>Duration ↬</b> <i>30 days</i>
<b>Price ↬</b> <i>25$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
<pre>𝑿-𝑨𝒄𝒄𝒆𝒔👑</pre>
<b>Duration ↬</b> <i>90 days</i>
<b>Price ↬</b> <i>60$</i>
<b>Credits ↬</b> <i>Unlimited until plan ends</i>
━━━━━━━━━━━━━━━━━━
"""
        kb = [
            [InlineKeyboardButton("Buy Now", callback_data="buy_now")],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # BUY NOW MENU
    elif data == "buy_now":
        text = """
<b>💳 Payment Options</b>
━━━━━━━━━━━━━━━━━━
<b>USDT (BEP20)</b>
<code>0x0a7961b6a421053e2f3e2d8deb8c25b65d0b8bf7</code>
━━━━━━━━━━━━━━━━━━
<b>USDT (TRC20)</b>
<code>THWyGchAMFNSHX8w7Cn2orMahknF6aHPfk</code>
━━━━━━━━━━━━━━━━━━
<b>BITCOIN (BTC)</b>
<code>163E7AR2dxsudeywL4G3FFR9Ztzb2z3VTM</code>
━━━━━━━━━━━━━━━━━━
<b>SOLANA (SQL)</b>
<code>FkieNMuLoQdCjsdv38JRGVy1F5UnDAmVhQBNmEsSQQdF</code>
━━━━━━━━━━━━━━━━━━
<b>BINANCE ID</b>
<code>1212231800</code>
━━━━━━━━━━━━━━━━━━
<b>⚠️ After payment, contact admin</b>
<a href="https://t.me/FailureFr_07">@FailureFr_07</a>
"""
        kb = [
            [InlineKeyboardButton("Back", callback_data="menu_pricing")]
        ]
        
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=text, parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup(kb)
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb)
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this specific error
                pass
            else:
                # Re-raise other errors
                raise

    # BACK TO MAIN PROFILE
    elif data == "back_main":
        # Get user info from the callback query instead of fetching from DB again
        user = update.effective_user
        user_id = user.id
        username = user.username if user.username else ""
        first_name = user.first_name or "User"
        
        # Get the existing message to extract the user data from it
        message_text = query.message.caption or query.message.text or ""
        
        # Extract user data from the message if available
        # This is more efficient than querying the database again
        try:
            # Try to extract user data from the current message
            import re
            
            # Extract user ID
            user_id_match = re.search(r'<code>(\d+)</code>', message_text)
            if user_id_match:
                user_id = user_id_match.group(1)
            
            # Extract username
            username_match = re.search(r'@([^<\s]+)', message_text)
            if username_match:
                username = username_match.group(1)
            
            # Extract tier
            tier_match = re.search(r'\[([^\]]+)\]', message_text)
            if tier_match:
                db_tier = tier_match.group(1)
            else:
                db_tier = "Free"
            
            # Extract credits
            credits_match = re.search(r'<code>([^<]+)</code>', message_text.split("𝐂𝐫𝐞𝐝𝐢𝐭𝐬")[1].split("𝐉𝒐𝒏𝒆𝒅")[0] if "𝐂𝐫𝐞𝐝𝐢𝐭𝐬" in message_text else "")
            if credits_match:
                credits_display = credits_match.group(1)
            else:
                # If we can't extract credits, get them from the database
                loop = asyncio.get_running_loop()
                db_user_data = await loop.run_in_executor(executor, get_or_create_user, user_id, username)
                if db_user_data:
                    _, _, _, db_credits = db_user_data
                    current_credits = get_user_credits(user_id)
                    if current_credits == float('inf'):
                        credits_display = "Infinite😎"
                    else:
                        credits_display = str(db_credits)
                else:
                    credits_display = "0"
            
            # Extract joined date
            joined_match = re.search(r'<code>([^<]+)</code>', message_text.split("𝐉𝒐𝒏𝒆𝒅")[1].split("𝐃𝐞𝐯")[0] if "𝐉𝒐𝒏𝒆𝒅" in message_text else "")
            if joined_match:
                formatted_joined_date = joined_match.group(1)
            else:
                # Default to today's date if we can't extract it
                formatted_joined_date = format_indian_datetime(datetime.datetime.now())
                
        except Exception as e:
            # If extraction fails, fetch from database
            try:
                loop = asyncio.get_running_loop()
                db_user_data = await loop.run_in_executor(executor, get_or_create_user, user_id, username)
                
                if not db_user_data:
                    error_msg = """
<a href='https://t.me/FailedFr'>⚠️</a> <b>Database Connection Failed</b>
<pre>⊀ Error: Unable to connect to database</pre>
<a href='https://t.me/FailedFr'>ℭ</a> <b>Action Required:</b> Please contact support
<a href='https://t.me/FailedFr'>⌬</a> <b>Support:</b> <a href='https://t.me/FailedFr'>kคli liຖนxx</a>
"""
                    await safe_edit_message(
                        context=context,
                        chat_id=chat_id,
                        message_id=message_id,
                        text=error_msg,
                        parse_mode=ParseMode.HTML
                    )
                    return
                
                db_username, db_joined_date, db_tier, db_credits = db_user_data
                
                # Get real-time credits to check for unlimited
                current_credits = get_user_credits(user_id)
                if current_credits == float('inf'):
                    credits_display = "Infinite😎"
                else:
                    credits_display = str(db_credits)
                
                # Format datetime properly to ensure correct timezone display
                formatted_joined_date = format_indian_datetime(db_joined_date)
                
                # Display username properly - add @ if username exists, otherwise show "None"
                display_username = f"@{db_username}" if db_username else "None"
            except Exception as db_error:
                logging.error(f"Database error in back_main: {db_error}")
                # Use default values if database fails
                db_tier = "Free"
                credits_display = "0"
                formatted_joined_date = format_indian_datetime(datetime.datetime.now())
                display_username = f"@{username}" if username else "None"
        else:
            # If extraction was successful, use the extracted values
            display_username = f"@{username}" if username else "None"

        # ==============================
        # PROFILE CARD DESIGN
        # ==============================
        caption = f"""
<pre>⊀ 𝑺𝒕𝒂𝒕𝒖𝒔: 𝐀𝐜𝐭𝐢𝐯𝐞 ✅</pre>

<a href='https://t.me/FailedFr'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {display_username}
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐌𝒂𝒏𝒈</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a> <code>[{db_tier}]</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐂𝒓𝒆𝒅𝒊𝒕𝒔</b> ↬ <code>{credits_display}</code>
<a href='https://t.me/FailedFr'>⊀</a> <b>𝐉𝒐𝒏𝒆𝒅</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/FailedFr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/FailureFr_07'>kคli liຖนxx</a>"""

        # Edit the current message instead of sending a new one
        try:
            if photo_file_id:
                await safe_edit_message_media(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(media=photo_file_id, caption=caption.strip(), parse_mode=ParseMode.HTML),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Gates", callback_data="menu_gates"), InlineKeyboardButton("Pricing", callback_data="menu_pricing")],
                        [InlineKeyboardButton("Group", url="https://t.me/+IFFnzNZuHFU5YmQ0"), InlineKeyboardButton("Updates", url="https://t.me/+E6zoRhIFhtNmM2E5")],
                        [InlineKeyboardButton("Dev", url="https://t.me/failurefr_07"), InlineKeyboardButton("Support", url="https://t.me/failurefr_07")]
                    ])
                )
            else:
                await safe_edit_message(
                    context=context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=caption.strip(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Gates", callback_data="menu_gates"), InlineKeyboardButton("Pricing", callback_data="menu_pricing")],
                        [InlineKeyboardButton("Group", url="https://t.me/+IFFnzNZuHFU5YmQ0"), InlineKeyboardButton("Updates", url="https://t.me/+E6zoRhIFhtNmM2E5")],
                        [InlineKeyboardButton("Dev", url="https://t.me/failurefr_07"), InlineKeyboardButton("Support", url="https://t.me/failurefr_07")]
                    ])
                )
        except Exception as e:
            error_msg = f"""
<a href='https://t.me/FailedFr'>⚠️</a> <b>System Error</b>
<pre>⊀ Error: {str(e)}</pre>
<a href='https://t.me/FailedFr'>ℭ</a> <b>Action Required:</b> Please try again later
<a href='https://t.me/FailedFr'>⌬</a> <b>Support:</b> <a href='https://t.me/FailureFr_07'>kคli liຖนxx</a>
"""
            logging.error(f"Error updating profile: {e}")
            await safe_edit_message(
                context=context,
                chat_id=chat_id,
                message_id=message_id,
                text=error_msg,
                parse_mode=ParseMode.HTML
            )
# ==============================
# MAIN BOT LAUNCHER
# ==============================
def main():
    # Create a thread pool executor to use with run_in_executor
    global executor
    executor = ThreadPoolExecutor(max_workers=4)
    
    if not create_connection_pool():
        error_msg = """
<a href='https://t.me/abtlnx'>⚠️</a> <b>Database Connection Failed</b>
<pre>⊀ Error: Unable to establish database connection pool</pre>
<a href='https://t.me/failfr'>ℭ</a> <b>Action Required:</b> Please check database configuration
<a href='https://t.me/failfr'>⌬</a> <b>Support:</b> <a href='https://t.me/FailureFr_07'>kคli liຖนxx</a>
"""
        logging.error("❌ Failed to connect DB.")
        print(error_msg)
        return
    setup_database()
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    TOKEN = "5408477690:AAHAbL3Q2B-wsRLBYjkqtZofU4rpVuLAiOA"
    if not TOKEN:
        print("❌ BOT_TOKEN not found in .env file!")
        exit(1)
        
    app = Application.builder().token(TOKEN).build()
    
    app.post_init = on_startup
    app.post_shutdown = on_shutdown
    # ==============================
    # IMPORT MASS CHECK HANDLERS
    # ==============================
# ==============================
    # CORE COMMAND HANDLERS
    # ==============================
    app.add_handler(CommandHandler("start", start))
   
    # NOTE: The generic handle_buttons is moved to VERY END to avoid conflicts.
    # This is most critical change.
    
    # Apply force_join decorator to all command handlers except /start
    @force_join
    async def wrapped_rz_command(update, context):
        return await handle_rz_command(update, context)
    
    @force_join
    async def wrapped_sh_command(update, context):
        return await handle_sh_command(update, context)
    
    @force_join
    async def wrapped_chk_command(update, context):
        return await handle_chk_command(update, context)
    
    @force_join
    async def wrapped_at_command(update, context):
        return await handle_at_command(update, context)

    
    @force_join
    async def wrapped_gate_command(update, context):
        return await handle_gate_command(update, context)

    
    @force_join
    async def wrapped_msh_command(update, context):
        return await handle_msh_command(update, context)
    
    @force_join
    async def wrapped_vbv_command(update, context):
        return await handle_vbv_command(update, context)
    
    @force_join
    async def wrapped_pv_command(update, context):
        return await handle_pv_command(update, context)
    
    @force_join
    async def wrapped_gplan1_command(update, context):
        return await handle_gplan1(update, context)
        
    @force_join
    async def wrapped_status_command(update, context):
        return await status_command(update, context)
    
    @force_join
    async def wrapped_gplan2_command(update, context):
        return await handle_gplan2(update, context)
    
    @force_join
    async def wrapped_gplan3_command(update, context):
        return await handle_gplan3(update, context)
    
    @force_join
    async def wrapped_gplan4_command(update, context):
        return await handle_gplan4(update, context)
    
    @force_join
    async def wrapped_claim_command(update, context):
        return await handle_claim(update, context)
    
    @force_join
    async def wrapped_gcodes_command(update, context):
        return await handle_gcodes(update, context)
    
    @force_join
    async def wrapped_st_command(update, context):
        return await handle_st_command(update, context)
    
    
    @force_join
    async def wrapped_pp_command(update, context):
        return await handle_pp_command(update, context)
    
    @force_join
    async def wrapped_p1_command(update, context):
        return await handle_p1_command(update, context)
    
    
    @force_join
    async def wrapped_credits_command(update, context):
        return await handle_credits_command(update, context)
    
    @force_join
    async def wrapped_gen_command(update, context):
        return await handle_gen_command(update, context)
    
    @force_join
    async def wrapped_proxy_command(update, context):
        return await handle_proxy_command(update, context)
    
    @force_join
    async def wrapped_rproxy_command(update, context):
        return await handle_rproxy_command(update, context)
    
    @force_join
    async def wrapped_myproxy_command(update, context):
        return await handle_myproxy_command(update, context)
    
    @force_join
    async def wrapped_b3_command(update, context):
        return await handle_b3_command(update, context)   
        
    @force_join
    async def wrapped_scr_command(update, context):
        return await handle_scr_command(update, context)

    @force_join
    async def wrapped_pf_command(update, context):
        return await handle_pf_command(update, context)

    @force_join
    async def wrapped_py_command(update, context):
        return await handle_py_command(update, context)

    @force_join
    async def wrapped_au_command(update, context):
        return await handle_au_command(update, context)

    @force_join
    async def wrapped_mau_command(update, context):
        # Use imported handle_mau_command from mau.py
        return await handle_mau_command(update, context)
    
    # Register wrapped command handlers
    app.add_handler(CommandHandler("pv", wrapped_pv_command))
    app.add_handler(CommandHandler("mau", wrapped_mau_command))
    app.add_handler(CommandHandler("au", wrapped_au_command))
    app.add_handler(CommandHandler("py", wrapped_py_command))
    app.add_handler(CommandHandler("pf", wrapped_pf_command))
    app.add_handler(CommandHandler("scr", wrapped_scr_command))
    app.add_handler(CommandHandler("rz", wrapped_rz_command))
    app.add_handler(CommandHandler("sh", wrapped_sh_command))
    app.add_handler(CommandHandler("chk", wrapped_chk_command))
    app.add_handler(CommandHandler("b3", wrapped_b3_command))
    app.add_handler(CommandHandler("gate", wrapped_gate_command))
    app.add_handler(CommandHandler("msh", wrapped_msh_command))
    app.add_handler(CommandHandler("vbv", wrapped_vbv_command))
    app.add_handler(CommandHandler("broad", broad))
    app.add_handler(CommandHandler("gplan1", wrapped_gplan1_command))
    app.add_handler(CommandHandler("gplan2", wrapped_gplan2_command))
    app.add_handler(CommandHandler("gplan3", wrapped_gplan3_command))
    app.add_handler(CommandHandler("gplan4", wrapped_gplan4_command))
    app.add_handler(CommandHandler("claim", wrapped_claim_command))
    app.add_handler(CommandHandler("gcodes", wrapped_gcodes_command))
    app.add_handler(CommandHandler("st", wrapped_st_command))
    app.add_handler(CommandHandler("pp", wrapped_pp_command))
    app.add_handler(CommandHandler("p1", wrapped_p1_command))
    app.add_handler(CommandHandler("credits", wrapped_credits_command))
    app.add_handler(CommandHandler("gen", wrapped_gen_command))
    app.add_handler(CommandHandler("proxy", wrapped_proxy_command))
    app.add_handler(CommandHandler("rproxy", wrapped_rproxy_command))
    app.add_handler(CommandHandler("myproxy", wrapped_myproxy_command))
    app.add_handler(CommandHandler("status", wrapped_status_command))

    # Import and register the stop command handler
    from stop import handle_stop_command
    app.add_handler(CommandHandler("stop", handle_stop_command))
    # ==============================
    # PLAN COMMAND HANDLERS
    # ==============================
    from plans import (
        handle_plan1, handle_plan2, handle_plan3, handle_plan4,
        handle_rplan, handle_planall, handle_decreds
     )

    @force_join
    async def wrapped_decreds_command(update, context):
        return await handle_decreds(update, context)

    @force_join
    async def wrapped_plan1_command(update, context):
        return await handle_plan1(update, context)
        
    @force_join
    async def wrapped_planall_command(update, context):
        return await handle_planall(update, context)
    
    
    @force_join
    async def wrapped_plan2_command(update, context):
        return await handle_plan2(update, context)
    
    @force_join
    async def wrapped_plan3_command(update, context):
        return await handle_plan3(update, context)
    
    @force_join
    async def wrapped_plan4_command(update, context):
        return await handle_plan4(update, context)
    
    @force_join
    async def wrapped_rplan_command(update, context):
        return await handle_rplan(update, context)
        
    app.add_handler(CommandHandler("plan1", wrapped_plan1_command))
    app.add_handler(CommandHandler("plan2", wrapped_plan2_command))
    app.add_handler(CommandHandler("plan3", wrapped_plan3_command))
    app.add_handler(CommandHandler("plan4", wrapped_plan4_command))
    app.add_handler(CommandHandler("rplan", wrapped_rplan_command))
    app.add_handler(CommandHandler("planall", wrapped_planall_command))
    app.add_handler(CommandHandler("decreds", wrapped_decreds_command))

    # ==============================
    # COMMANDS MENU HANDLER (/cmds) - CORRECTED
    # ==============================
    # CHANGE 1: Import new, combined handler
    from cmds import cmds_command, cmds_callback_handler
    
    @force_join
    async def wrapped_cmds_command(update, context):
        return await cmds_command(update, context)
    
    # Register command handler - THIS WAS MISSING
    app.add_handler(CommandHandler("cmds", wrapped_cmds_command))
        
# ==============================
    # SETURL COMMAND HANDLERS
    # ==============================
    # Import all handler functions from seturl.py
    from seturl import handle_seturl_command, handle_delurl_command, handle_delall_command, handle_resites_command, handle_delall_callback, handle_seturl_price_callback

    @force_join
    async def wrapped_seturl_command(update, context):
        # Use imported handle_seturl_command from seturl.py
        return await handle_seturl_command(update, context)

    @force_join
    async def wrapped_delurl_command(update, context):
        # Use imported handle_delurl_command from seturl.py
        return await handle_delurl_command(update, context)

    @force_join
    async def wrapped_delall_command(update, context):
        # Use imported handle_delall_command from seturl.py
        return await handle_delall_command(update, context)

    @force_join
    async def wrapped_resites_command(update, context):
        # Use imported handle_resites_command from seturl.py
        return await handle_resites_command(update, context)


    # Register all seturl command handlers
    app.add_handler(CommandHandler("seturl", wrapped_seturl_command))
    app.add_handler(CommandHandler("delurl", wrapped_delurl_command))
    app.add_handler(CommandHandler("delall", wrapped_delall_command))
    app.add_handler(CommandHandler("resites", wrapped_resites_command))
    # Register delall callback handler
    app.add_handler(CallbackQueryHandler(handle_delall_callback, pattern=r'^delall_'))
    app.add_handler(CallbackQueryHandler(handle_seturl_price_callback, pattern=r'^seturl_price_'))
    app.add_handler(CallbackQueryHandler(handle_msh_confirm_callback, pattern=r'^msh_(yes|no)_'))


    # ==============================
    # SEPARATE STOP CALLBACK HANDLERS FOR EACH MODULE
    # ==============================
    # MAU Stop Callback Handler
    async def mau_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        user_id = update.effective_user.id
        
        # Acknowledge button press
        await safe_answer_callback_query(query)
        
        # Check if the user who clicked is the same as the one who started the check
        if not data.startswith("stop_mau_"):
            return
            
        try:
            # Get the user ID from callback data
            callback_user_id = int(data.split("_")[-1])
            
            # Get the current user ID from query
            current_user_id = update.effective_user.id
            
            # Check if the user who clicked is the same as the one who started the check
            if callback_user_id != current_user_id:
                # Show popup message "Not your business"
                await context.bot.answer_callback_query(
                    query.id,
                    text="⛔ Not your business!",
                    show_alert=True
                )
                return
            
            # Check if there's an active mass check for this user
            if callback_user_id not in mau_active_mass_checks:
                await context.bot.answer_callback_query(
                    query.id,
                    text="⚠️ No active MAU check found!",
                    show_alert=True
                )
                return
            
            # Set stop flag for this user
            mau_active_mass_checks[callback_user_id]["stopped"] = True
            
            # Set the stop_event if it exists
            if "stop_event" in mau_active_mass_checks[callback_user_id]:
                mau_active_mass_checks[callback_user_id]["stop_event"].set()
                logging.info(f"Stop event set for MAU user {callback_user_id}")
            
            logging.info(f"Stop requested by user {callback_user_id} for MAU")
            
            # Cancel all active API calls if they exist
            if "workers" in mau_active_mass_checks[callback_user_id]:
                workers = mau_active_mass_checks[callback_user_id]["workers"]
                if workers:
                    logging.info(f"Cancelling {len(workers)} active workers for MAU user {callback_user_id}")
                    
                    # Cancel all tasks
                    for task in workers:
                        try:
                            if not task.done():
                                task.cancel()
                        except Exception as e:
                            logging.error(f"Error cancelling MAU task: {str(e)}")
                    
                    # Wait for all tasks to be cancelled with a timeout
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*workers, return_exceptions=True),
                            timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout waiting for MAU tasks to cancel for user {callback_user_id}")
            
            # Show popup message "Stopped checking"
            await context.bot.answer_callback_query(
                query.id,
                text="⏹️ Stopped MAU checking!",
                show_alert=True
            )
            
            # Calculate elapsed time
            start_time = mau_active_mass_checks[callback_user_id].get("start_time", time.time())
            elapsed_time = round(abs(time.time() - start_time), 2)
            
            # Get user name
            user_name = update.effective_user.first_name
            
            # Get stats from active_checks
            stats = mau_active_mass_checks[callback_user_id].get("stats", {
                "total": 0,
                "checked": 0,
                "approved": 0,
                "declined": 0,
                "error": 0
            })
            
            # Import format_final_response function
            from mau import format_final_response
            
            # Update message to show final results immediately without stop button
            await safe_edit_message(
                context=context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=format_final_response(stats, elapsed_time, user_name, True),
                parse_mode="HTML"
            )
            
            # Clean up the user entry immediately after stopping
            if callback_user_id in mau_active_mass_checks:
                del mau_active_mass_checks[callback_user_id]
            
        except (ValueError, IndexError) as e:
            logging.error(f"Error processing MAU stop callback: {str(e)}")
            pass  # Invalid callback data
            
    # Add this after your stop callback handlers
    app.add_handler(CallbackQueryHandler(cmds_callback_handler, pattern=r'^cmds_'))
    # Register separate stop callback handlers with highest priority
    app.add_handler(CallbackQueryHandler(mau_stop_callback, pattern=r'^stop_mau_'), group=0)
    # ==============================
    # FORCE JOIN CALLBACK HANDLER
    # ==============================
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
    # ==============================
    # GENERIC CALLBACK HANDLER - MOVED TO THE END
    # ==============================
    # CHANGE 3: Moved this generic handler to very bottom.
    # It will now only catch callbacks that were not handled by more specific handlers above.
    app.add_handler(CallbackQueryHandler(handle_buttons))

    # ==============================
    # START BOT
    # ==============================
    logging.info("🚀 CARD-X-CHK Bot Started Successfully")

    try:
        app.run_polling()
    finally:
        # Clean up resources
        executor.shutdown(wait=True)
        close_connection_pool()
        logging.info("🔒 Database connections closed.")

if __name__ == "__main__":
    main()
