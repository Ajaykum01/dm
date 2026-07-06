import re
import os
import asyncio
import logging
import aiofiles
import html
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError
from database import get_or_create_user, update_user_credits, get_user_credits
from plans import get_user_current_tier

# Hardcoded API credentials (as requested)
API_ID = 20983135
API_HASH = "d63005abdb9cf5ed0cb76c231a6ef699"
BOT_TOKEN = "8001170085:AAF0kqCuN-Uo6rkxeW5LtI943OSmJ7FdRbE"
SESSION_STRING = "AQJQHbUAwn_Y158TYVmQGDHtvWEB90fe4oC-TJvf8vmvVZt-e2HwWeviX3QiKudGpXIIijLPz_h4UeingCXbqZRxZmjPiyaTMhQP7Al-H4rkK89KPHndTRAxFEZO95sFAnX6t80Z0N2AhAg-AnWRt4fG2YKpwaWcJqHcn1g9641wrgqVuJ2-ne9O8_la5ECi9QhMVBMojTT7gsCo_SlJYeZA65IUJzyMdJfzC9pnxTQMdsJXcPBG-jmNx1A-vDus4Qj5fl0gW_aa5wG3bxif9jDTPpEK5JVgvuk7E4_PY7Ry41d8hCbX2TaZV3RIOGDYgf5y7YNSiqTMVt2pYgB-UlRAErmDRQAAAAHraX5JAA"

# Hardcoded limits and settings (as requested)
DEFAULT_LIMIT = 2000  # Card Scrapping Limit For Free/Trial Users
PREMIUM_LIMIT = 7000  # Card Scrapping Limit For Premium Users
COOLDOWN_FREE = 10  # Cooldown for Free/Trial users (in seconds)
COOLDOWN_TRIAL = 10  # Cooldown for Trial users (in seconds)
CREDIT_COST = 2  # Credits deducted for each successful command

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Pattern to find credit card details
CARD_PATTERN = r'\d{13,19}\D*\d{1,2}\D*\d{2,4}\D*\d{3,4}'

# Import Pyrogram for scraping functionality
try:
    from pyrogram import Client as PyrogramClient, filters as PyrogramFilters
    from pyrogram.errors import (
        UserAlreadyParticipant,
        InviteHashExpired,
        InviteHashInvalid,
        PeerIdInvalid,
        InviteRequestSent
    )
    from pyrogram.enums import ParseMode as PyrogramParseMode
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    PYROGRAM_AVAILABLE = True
except ImportError:
    logger.warning("Pyrogram not available, scraping functionality will be limited")
    PYROGRAM_AVAILABLE = False

# Initialize Pyrogram client for scraping if available
if PYROGRAM_AVAILABLE:
    user_client = PyrogramClient(
        "user_session",
        session_string=SESSION_STRING,
        workers=1000
    )
else:
    user_client = None

# Function to extract and format card details from text
def extract_and_format_cards(text: str) -> List[str]:
    """
    Extract and format credit card details from text.
    
    Args:
        text: Text to search for card details
        
    Returns:
        List of formatted card strings
    """
    cards = []
    matches = re.findall(CARD_PATTERN, text)
    
    for match in matches:
        # Extract digits from the match
        digits = re.findall(r'\d+', match)
        if len(digits) >= 4:
            card_number = digits[0]
            month = digits[1].zfill(2)  # Ensure month is 2 digits
            year = digits[2]
            cvv = digits[3]
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
                
            cards.append(f"{card_number}|{month}|{year}|{cvv}")
    
    return cards

# Function to remove duplicates from a list
def remove_duplicates(cards: List[str]) -> tuple:
    """
    Remove duplicates from a list of cards.
    
    Args:
        cards: List of card strings
        
    Returns:
        Tuple of (unique_cards, duplicates_removed)
    """
    unique_cards = list(set(cards))
    duplicates_removed = len(cards) - len(unique_cards)
    return unique_cards, duplicates_removed

# Function to format the response message
def format_scr_response(results: Dict, user_info: Dict) -> str:
    """
    Format the scraping results into a beautiful message.
    
    Args:
        results: Dictionary containing scraping results
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string with emojis
    """
    success = results.get("success", False)
    if not success:
        error_msg = results.get('error', 'Unknown error')
        formatted_error = f"⚠️ <b>Error scraping cards</b>: <code>{html.escape(error_msg)}</code>"
        return formatted_error
    
    cards_found = results.get("cards_found", 0)
    duplicates_removed = results.get("duplicates_removed", 0)
    source = results.get("source", "Unknown")
    bin_filter = results.get("bin_filter", "")
    bank_filter = results.get("bank_filter", "")
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Get user credits and format display
    user_credits = get_user_credits(user_id)
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"  # Display for unlimited credits
    else:
        credits_display = str(user_credits)
    
    # Create user link with profile name hyperlinked
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝑪𝒐𝒎𝒑𝒍𝒆𝒕𝒆𝒅</b> ✅</pre>"""
    
    source_part = f"""<a href='https://t.me/failfr'>⌬</a> <b>𝑺𝒐𝒖𝒓𝒄𝒆</b> ↬ <code>{source}</code>"""
    
    # Use bullet points for cards found and duplicates removed
    cards_part = f"""<a href='https://t.me/failfr'>⊀</a> <b>𝑪𝒂𝒓𝒅𝒔 𝑭𝒐𝒖𝒏𝒅</b> ↬ <code>{cards_found}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝑫𝒖𝒑𝒍𝒊𝒄𝒂𝒕𝒆𝒔 𝑹𝒆𝒎𝒐𝒗𝒆𝒅</b> ↬ <code>{duplicates_removed}</code>"""
    
    filter_part = ""
    if bin_filter:
        filter_part += f"<a href='https://t.me/failfr'>⊀</a> <b>𝑩𝑰𝑵 𝑭𝒊𝒍𝒕𝒆𝒓</b> ↬ <code>{bin_filter}</code>"
    if bank_filter:
        filter_part += f"<a href='https://t.me/failfr'>⊀</a> <b>𝑩𝒂𝒏𝒌 𝑭𝒊𝒍𝒕𝒆𝒓</b> ↬ <code>{bank_filter}</code>"
    
    # Add credits info only if user has 0 credits and not unlimited
    credits_warning = ""
    if user_credits is not None and user_credits <= 0 and user_credits != float('inf'):
        credits_warning = f"\n<a href='https://t.me/failfr'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
    
    # Combine all parts
    formatted_response = f"""{status_part}
{source_part}
{cards_part}
{filter_part}
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failfr'>kคli liຖนxx</a>
{credits_warning}"""
    
    return formatted_response

# Function to safely send messages with retry logic (from main.py)
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

# Function to safely edit messages with retry logic (from main.py)
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

# Function to join private chat using Pyrogram
async def join_private_chat(client, invite_link):
    try:
        await client.join_chat(invite_link)
        logger.info(f"Joined chat via invite link: {invite_link}")
        return True
    except UserAlreadyParticipant:
        logger.info(f"Already a participant in the chat: {invite_link}")
        return True
    except InviteRequestSent:
        logger.info(f"Join request sent to the chat: {invite_link}")
        return False
    except (InviteHashExpired, InviteHashInvalid) as e:
        logger.error(f"Failed to join chat {invite_link}: {e}")
        return False

# Function to initialize Pyrogram client
async def initialize_pyrogram():
    """Initialize the Pyrogram client for scraping"""
    if PYROGRAM_AVAILABLE:
        try:
            # Create the client if it doesn't exist
            if user_client is None:
                user_client = PyrogramClient(
                    "user_session",
                    session_string=SESSION_STRING,
                    workers=1000
                )
            
            # Start the client with timeout
            await user_client.start()
            logger.info("Pyrogram client started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start Pyrogram client: {e}")
            logger.error(f"Pyrogram initialization failed: {str(e)}")
            logger.error(f"Session string length: {len(SESSION_STRING)}")
            logger.error(f"Pyrogram version: {pyrogram.__version__ if 'pyrogram' in globals() else 'unknown'}")
            return False
    return False

# Function to scrape messages using Pyrogram
async def scrape_messages(client, channel_identifier, limit, start_number=None, bank_name=None):
    messages = []
    count = 0
    pattern = r'\d{13,19}\D*\d{1,2}\D*\d{2,4}\D*\d{3,4}'
    bin_pattern = re.compile(r'^\d{6}') if start_number else None

    logger.info(f"Starting to scrape messages from {channel_identifier} with limit {limit}")

    # Fetch messages in batches
    async for message in client.search_messages(channel_identifier):
        if count >= limit:
            break
        text = message.text or message.caption
        if text:
            # Check if the bank name is mentioned in the message (case-insensitive)
            if bank_name and bank_name.lower() not in text.lower():
                continue
            matched_messages = re.findall(pattern, text)
            if matched_messages:
                formatted_messages = []
                for matched_message in matched_messages:
                    extracted_values = re.findall(r'\d+', matched_message)
                    if len(extracted_values) == 4:
                        card_number, mo, year, cvv = extracted_values
                        year = year[-2:]
                        # Apply BIN filter if start_number is provided
                        if start_number:
                            if card_number.startswith(start_number[:6]):
                                formatted_messages.append(f"{card_number}|{mo}|{year}|{cvv}")
                        else:
                            formatted_messages.append(f"{card_number}|{mo}|{year}|{cvv}")
                messages.extend(formatted_messages)
                count += len(formatted_messages)
    logger.info(f"Scraped {len(messages)} messages from {channel_identifier}")
    return messages[:limit]

# Function to handle the /scr command
async def handle_scr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /scr command with user-specific cooldown for Trial users.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    logger.info(f"User {username} (ID: {user_id}) initiated /scr command")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    logger.info(f"User tier: {user_tier}")
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        cooldown_seconds = COOLDOWN_TRIAL if user_tier == "Trial" else COOLDOWN_FREE
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=cooldown_seconds):
            remaining_seconds = cooldown_seconds - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Parse command arguments
    args = context.args
    logger.info(f"Command arguments: {args}")
    
    if len(args) < 2:
        await update.message.reply_text(
            "⚠️ <b>Missing arguments!</b>\n\n"
            "<i>Usage: /scr [channel] [limit] [bin/bank]</i>\n"
            "<i>Example: /scr @channel 100 515462</i>\n"
            "<i>Example: /scr @channel 100 BankName</i>", 
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get user credits BEFORE processing
    user_credits = get_user_credits(user_id)
    logger.info(f"User credits: {user_credits}")
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/abtlnx'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/failfr'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/failfr'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/failfr'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Extract channel identifier
    channel_identifier = args[0]
    channel_id = None
    channel_name = "Unknown"
    channel_username = None
    
    logger.info(f"Processing channel identifier: {channel_identifier}")
    
    # Handle private channel chat ID (numeric)
    if channel_identifier.lstrip("-").isdigit():
        # Treat it as a chat ID
        try:
            # Fetch the chat details using python-telegram-bot
            chat = await context.bot.get_chat(channel_identifier)
            channel_name = chat.title
            channel_id = int(channel_identifier)
            channel_username = chat.username  # Get the username if available
            logger.info(f"Successfully resolved chat ID: {channel_id}, name: {channel_name}, username: {channel_username}")
        except Exception as e:
            logger.error(f"Error resolving chat ID {channel_identifier}: {str(e)}")
            await update.message.reply_text(f"<b>Invalid chat ID ❌</b>\n\n<code>{html.escape(str(e))}</code>")
            return
    else:
        # Handle public channels or private invite links
        if channel_identifier.startswith("https://t.me/+"):
            # Private invite link
            invite_link = channel_identifier
            try:
                if PYROGRAM_AVAILABLE and user_client:
                    # Fix: Wrap join_chat to specifically catch UserAlreadyParticipant
                    try:
                        await user_client.join_chat(invite_link)
                    except UserAlreadyParticipant:
                        logger.info(f"Already a participant in the chat: {invite_link}")
                    except InviteRequestSent:
                        logger.info(f"Join request sent to the chat: {invite_link}")
                    
                    # Attempt to get chat details (works if we are joined or just requested)
                    chat = await user_client.get_chat(invite_link)
                    channel_name = chat.title
                    channel_id = chat.id
                    channel_username = chat.username
                    logger.info(f"Successfully processed private channel: {channel_name}, ID: {channel_id}, username: {channel_username}")
                else:
                    # Fallback if Pyrogram is not available
                    try:
                        await context.bot.join_chat(invite_link)
                    except BadRequest as e:
                        if "USER_ALREADY_PARTICIPANT" in str(e):
                            logger.info(f"Bot already a participant in the chat: {invite_link}")
                        else:
                            raise
                    
                    chat = await context.bot.get_chat(invite_link)
                    channel_name = chat.title
                    channel_id = chat.id
                    channel_username = chat.username
                    logger.info(f"Successfully processed private channel: {channel_name}, ID: {channel_id}, username: {channel_username}")
            except Exception as e:
                # This catches actual critical errors (e.g. InviteHashExpired)
                logger.error(f"Error joining private channel {invite_link}: {str(e)}")
                await update.message.reply_text(f"<b>Failed to join private channel ❌</b>\n\n<code>{html.escape(str(e))}</code>")
                return
        elif channel_identifier.startswith("https://t.me/"):
            # Remove "https://t.me/" for regular links
            channel_username = channel_identifier[13:]
        elif channel_identifier.startswith("t.me/"):
            # Remove "t.me/" for short links
            channel_username = channel_identifier[5:]
        else:
            # Assume it's already a username
            channel_username = channel_identifier

        if channel_id is None:
            # Ensure the username starts with @ for the API
            if not channel_username.startswith("@"):
                channel_username = "@" + channel_username
                
            logger.info(f"Attempting to get chat with username: {channel_username}")
            
            try:
                # Fetch the chat details using python-telegram-bot
                chat = await context.bot.get_chat(channel_username)
                channel_name = chat.title
                channel_id = chat.id
                channel_username = chat.username
                logger.info(f"Successfully resolved channel: {channel_name}, ID: {channel_id}, username: {channel_username}")
            except Exception as e:
                logger.error(f"Error resolving channel {channel_username}: {str(e)}")
                await update.message.reply_text(f"<b>Incorrect username or chat ID ❌</b>\n\n<code>{html.escape(str(e))}</code>")
                return
    
    # Extract limit (second argument)
    try:
        limit = int(args[1])
        logger.info(f"Limit set to: {limit}")
    except ValueError:
        logger.error(f"Invalid limit value: {args[1]}")
        await update.message.reply_text(
            "<b>⚠️ Invalid limit value ❌</b>\n\n"
            "<i>Please provide a valid number for the limit parameter.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Enforce maximum limit based on user tier
    max_limit = PREMIUM_LIMIT if user_tier != "Free" and user_tier != "Trial" else DEFAULT_LIMIT
    if limit > max_limit:
        await update.message.reply_text(
            f"<b>⚠️ Maximum limit exceeded ❌</b>\n\n"
            f"<i>Your current plan allows a maximum of {max_limit} cards.</i>\n"
            f"<i>Please reduce your limit or upgrade your plan.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Extract optional filter (third argument)
    bin_filter = None
    bank_filter = None
    if len(args) > 2:
        # Check if the third argument is a BIN number (digits only)
        if args[2].isdigit():
            bin_filter = args[2]
            logger.info(f"BIN filter applied: {bin_filter}")
        else:
            # Otherwise, treat it as a bank name
            bank_filter = " ".join(args[2:])
            logger.info(f"Bank filter applied: {bank_filter}")
    
    # Create progress message with proper clickable bullets
    progress_msg = f"""<pre><b>𝗦𝗰𝗿𝗮𝗽𝗶𝗻𝗴 𝗜𝗻 𝗣𝗿𝗼𝗴𝗿𝗲𝘀𝘀...</b></pre>
<a href='https://t.me/failfr'>⊀</a> <b>𝑺𝒐𝒖𝒓𝒄𝒆</b> ↬ <code>{channel_name}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝑳𝒊𝒎𝒊𝒕</b> ↬ <code>{limit}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝑭𝒊𝒍𝒕𝒆𝒓</b> ↬ <code>{bin_filter or bank_filter or 'None'}</code>"""
    
    # Send the progress message
    scraping_message = await update.message.reply_text(progress_msg, parse_mode=ParseMode.HTML)
    logger.info(f"Sent progress message to user {user_id}")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
        logger.info(f"Updated last command time for user {user_id}")
    
    # Create a background task for the scraping to avoid blocking
    async def background_scrape():
        try:
            logger.info(f"Starting background scraping for channel {channel_id} with limit {limit}")
            
            # Check if Pyrogram is available and connected
            if not PYROGRAM_AVAILABLE or not user_client or not user_client.is_connected:
                raise RuntimeError("Scraping service is unavailable. Pyrogram client is not running.")
            
            # Use Pyrogram for scraping - pass the username, not the numeric ID
            pyrogram_channel_identifier = channel_username if channel_username else str(channel_id)
            scrapped_results = await scrape_messages(
                user_client, 
                pyrogram_channel_identifier, 
                limit, 
                start_number=bin_filter, 
                bank_name=bank_filter
            )
            unique_cards, duplicates_removed = remove_duplicates(scrapped_results)
            
            logger.info(f"Found {len(unique_cards)} unique cards, removed {duplicates_removed} duplicates")
            
            # Prepare results
            results = {
                "success": True if unique_cards else False,
                "cards_found": len(unique_cards),
                "duplicates_removed": duplicates_removed,
                "source": channel_name,
                "bin_filter": bin_filter or "",
                "bank_filter": bank_filter or ""
            }
            
            # If cards were found, create a file with the results
            if unique_cards:
                file_name = f"x{len(unique_cards)}_{channel_name.replace(' ', '_')}.txt"
                logger.info(f"Creating file with results: {file_name}")
                
                # Use aiofiles for asynchronous file writing
                async with aiofiles.open(file_name, mode='w') as f:
                    await f.write("\n".join(unique_cards))
                
                # Use aiofiles for asynchronous file reading
                async with aiofiles.open(file_name, mode='rb') as f:
                    # Deduct credits based on config if the response was successful and user doesn't have unlimited credits
                    if not is_unlimited:
                        update_user_credits(user_id, -CREDIT_COST)
                        logger.info(f"Deducted {CREDIT_COST} credits from user {user_id}")
                        
                        # Get updated credits for the response
                        updated_credits = get_user_credits(user_id)
                        logger.info(f"Updated user credits: {updated_credits}")
                        
                        # Add warning if credits are now 0
                        if updated_credits is not None and updated_credits <= 0:
                            results["credits_warning"] = True
                    
                    # Format the response
                    formatted_response = format_scr_response(results, user_info)
                    
                    # Send the file with caption
                    await context.bot.send_document(
                        update.effective_chat.id,
                        document=file_name,
                        caption=formatted_response,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"Sent results file to user {user_id}")
                
                # Remove the file
                os.remove(file_name)
                logger.info(f"Removed temporary file: {file_name}")
                
                # Delete the scraping message
                await scraping_message.delete()
                logger.info(f"Deleted progress message")
            else:
                # No cards found
                results["success"] = False
                results["error"] = "No credit cards found"
                formatted_response = format_scr_response(results, user_info)
                await safe_edit_message(
                    context=context,
                    chat_id=update.effective_chat.id,
                    message_id=scraping_message.message_id,
                    text=formatted_response,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"No cards found, updated message with error")
        
        except RuntimeError as e:
            logger.error(f"Pyrogram not available: {str(e)}")
            error_msg = f"⚠️ <b>Scraper offline</b>\n<code>{html.escape(str(e))}</code>"
            await safe_edit_message(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=scraping_message.message_id,
                text=error_msg,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error in background scraping: {str(e)}", exc_info=True)
            error_msg = f"⚠️ <b>Error:</b> <code>{html.escape(str(e))}</code>"
            await safe_edit_message(
                context=context,
                chat_id=update.effective_chat.id,
                message_id=scraping_message.message_id,
                text=error_msg,
                parse_mode=ParseMode.HTML
            )
    
    # Schedule the background task without awaiting it
    asyncio.create_task(background_scrape())
    logger.info(f"Background scraping task created for user {user_id}")

# Function to initialize Pyrogram client
async def initialize_pyrogram():
    """Initialize the Pyrogram client for scraping"""
    if PYROGRAM_AVAILABLE and user_client:
        try:
            # Start the client with timeout
            await user_client.start()
            logger.info("Pyrogram client started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start Pyrogram client: {e}")
            logger.error(f"Error details: {str(e)}")
            logger.error(f"Session string length: {len(SESSION_STRING)}")
            return False
    return False

# Function to stop Pyrogram client
async def stop_pyrogram():
    """Stop the Pyrogram client"""
    if PYROGRAM_AVAILABLE and user_client:
        try:
            await user_client.stop()
            logger.info("Pyrogram client stopped successfully")
        except Exception as e:
            logger.error(f"Failed to stop Pyrogram client: {e}")

# Export the necessary functions
__all__ = [
    'handle_scr_command',
    'initialize_pyrogram',
    'stop_pyrogram'
]
