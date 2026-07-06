import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import TelegramError

ADMIN_ID = 7758558590 

# ==============================
# LOGGING CONFIGURATION
# ==============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# HELPER FUNCTIONS
# ==============================
def escape_html(text: str) -> str:
    """Escape HTML to prevent Telegram parse errors."""
    return html.escape(text, quote=False)

# ==============================
# COMMAND LIST
# ==============================
ALL_COMMANDS = [
    ("PayFast 0.30$", "/pf", "Free", "PayFast 0.30$ Charge", "pf"),
    ("Stripe Auth", "/au", "Free", "Stripe Auth", "au"),
    ("Mass Stripe Auth", "/mau", "Free", "Mass Stripe Auth", "mau"),
    ("scrapper", "/scr", "Free", "cards scrapper", "scr"),
    ("Braintree Auth", "/chk", "Free", "Single Braintree Auth", "chk"),
    ("Authnet 1$ Charge", "/at", "Free", "Authnet 1$ Charge Gateway", "at"),
    ("Paypal 1$ Charge", "/pp", "Free", "Paypal 1$ Charge Gateway", "pp"),
    ("SK Based 1$ charge", "/sk", "Free", "SK BASED 1$", "sk"),
    ("Payu 0.29$ Charge", "/py", "Paid", "PayU 0.29$ Charge Gateway", "py"),
    ("Payu €  Charge", "/pu", "Paid", "PayU 1€ Charge Gateway", "pu"),
    ("Set you sites", "/seturl", "Paid", "Autoshopify site add.", "seturl"),
    ("Delete your site", "/delurl", "Paid", "Site remover", "delurl"),
    ("Remove your all sites", "/delall", "Paid", "Site remover", "delall"),
    ("3DS Lookup", "/vbv", "Free", "3DS Lookup Gateway", "vbv"),
    ("Shopify Charge $1", "/sh", "Free", "Shopify 1$ Charge Gateway", "sh"),
    ("Razorpay charge 1₹", "/rz", "Free", "Razorpay 1₹ Charge Gateway", "rz"),
    ("Mass Shopify Charged", "/msh", "Paid", "Mass Shopify Charge Gateway", "msh"),
    ("Mass SK BASED 1$ Charged", "/msk", "Paid", "Mass sk based Charge Gateway", "msk"),
    ("Mass Braintree Auth", "/mtxt", "Paid", "Mass Braintree Auth Gateway", "mtxt"),
    ("Generate ccs", "/gen", "Free", "CCs generator", "gen"),
    ("Redeem a bot code", "/claim", "Free", "Redeem Bot Code", None),
    ("Check your remaining credits", "/credits", "Free", "Credits Check", None),
    ("Payment Gateway Checker", "/gate", "Free", "Payment Gateway Status", "gate"),
    ("Add your proxy", "/proxy", "Free", "Proxy adder", "proxy"),
    ("Remove your proxies", "/rproxy", "Free", "Proxy remover", "rproxy"),    
    ("Your proxy viewer", "/myproxy", "Free", "Check your added proxies", "myproxy"),    
]

# ==============================
# PAGINATION SETUP
# ==============================
PAGE_SIZE = 4
PAGES = [ALL_COMMANDS[i:i + PAGE_SIZE] for i in range(0, len(ALL_COMMANDS), PAGE_SIZE)]


# ==============================
# PAGE BUILDER
# ==============================
async def build_page_text(page_index: int, user_id: int) -> str:
    """Build formatted command list for a given page in the new UI style."""
    try:
        page_commands = PAGES[page_index]
        
        # Main Header
        text = f"<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑨𝒖𝒂𝒊𝒎𝒂𝒏𝒅𝒔 𝑪𝒐𝒎𝒎𝒂𝒏𝒅𝒔</b> ↬ <i>Page {page_index + 1}/{len(PAGES)}</i></pre>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"

        for name, cmd, cmd_type, desc, gate_name in page_commands:
            # Conditional lock emoji: only show for Paid commands
            type_emoji = "🔒" if cmd_type == "Paid" else ""
            
            # Status is now static for all commands
            status = "Online ✅"
            
            # Command block with the new styling
            text += f"<pre><a href='https://t.me/abtlnx'>⊀</a> <b>𝑵𝒂𝒎𝒆</b> ↬ <i>{escape_html(name)}</i></pre>\n"
            text += f"<a href='https://t.me/failfr'>⊀</a> <b>𝑪𝒐𝒎𝒎𝒂𝒏𝒅</b> ↬ <i>{escape_html(cmd)}</i>\n"
            text += f"<a href='https://t.me/failfr'>⊀</a> <b>𝑰𝒏𝒇𝒐</b> ↬ <i>{escape_html(desc)}</i>\n"
            text += f"<a href='https://t.me/failfr'>⊀</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <i>{status}</i>\n"
            text += f"<a href='https://t.me/failfr'>⊀</a> <b>𝑻𝒚𝒑𝒆</b> ↬ <i>{type_emoji} {cmd_type}</i>\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n"
            
        return text.strip()
    except Exception as e:
        logger.error(f"Error building page text: {e}")
        return "Error: Could not build page text."


def build_cmds_buttons(page_index: int) -> InlineKeyboardMarkup:
    """Generate pagination + close buttons."""
    buttons = []
    nav_buttons = []
    # Use specific callback data to avoid conflicts
    if page_index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Back", callback_data=f"cmds_page_{page_index - 1}"))
    if page_index < len(PAGES) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"cmds_page_{page_index + 1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="cmds_close")])
    return InlineKeyboardMarkup(buttons)


# ==============================
# COMMAND HANDLERS
# ==============================

async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cmds command."""
    user_id = update.effective_user.id
    text = await build_page_text(0, user_id)
    buttons = build_cmds_buttons(0)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=buttons
    )


# This single handler now manages all callbacks from /cmds menu
async def cmds_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses from the /cmds command menu."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data.startswith("cmds_page_"):
        try:
            page_index = int(data.split("_")[2])
            text = await build_page_text(page_index, user_id)
            buttons = build_cmds_buttons(page_index)
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=buttons
            )
        except TelegramError as e:
            # Silently handle the case where the message text is not modified
            if "Message is not modified" in str(e):
                pass
            else:
                logger.error(f"TelegramError in pagination: {e}")
        except (IndexError, ValueError) as e:
            logger.error(f"Invalid page data in callback: {data} - {e}")
        except Exception as e:
            logger.error(f"Unexpected error in pagination: {e}")

    elif data == "cmds_close":
        try:
            await query.message.delete()
        except TelegramError as e:
            logger.error(f"Could not delete message: {e}")
            # Fallback if deletion fails (e.g., message is too old)
            await query.edit_message_text("Menu closed.")
