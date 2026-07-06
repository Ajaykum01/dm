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

# API endpoint - Updated to charge.cxchk.site
API_BASE_URL = "https://stripe1.nikhilkhokhar.com"

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Dictionary to track active requests per user (REMOVED as per request to allow multiple concurrent requests)

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

async def check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card details using Stripe 0.50$ API asynchronously with aiohttp.
    Updated to parse API response: {"status": "...", "message": "...", "decline_code": "..."}
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Formatted response string or None if there was an error
    """
    # Parse card details
    parsed = parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /st card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Construct the card string for the API
    card_string = f"{card_number}|{month}|{year}|{cvv}"
    
    # Construct the API URL
    api_url = f"{API_BASE_URL}/gate=stripe/cc={card_string}"
    
    try:
        # Create an aiohttp session for async HTTP requests
        async with aiohttp.ClientSession() as session:
            # Make API request asynchronously
            async with session.get(api_url, timeout=30) as response:
                # Get the response status code
                status_code = response.status
                
                # Try to parse as JSON, but handle cases where it's not valid JSON
                try:
                    api_response = await response.json()
                except:
                    # If it's not valid JSON, try to get text
                    response_text = await response.text()
                    api_response = {
                        "status": "Error",
                        "message": response_text,
                        "decline_code": "unknown"
                    }
        
        # --- Updated Response Processing Logic ---
        
        # Extract fields from the new API structure safely
        # Expected format: {"status": "Charged/Approved/Declined", "message": "...", "decline_code": "..."}
        
        status_val = str(api_response.get("status", "Unknown")).lower()
        msg_val = api_response.get("message", "N/A")
        decline_code_val = api_response.get("decline_code", "N/A")
        
        # Construct the formatted response string: Message (Decline Code)
        # Example: "Your payment was successful (succeeded)"
        formatted_api_response = f"{msg_val} ({decline_code_val})"
        
        # Determine Status Text and Emoji based on API Status
        if "charged" in status_val or "success" in status_val or "captured" in status_val:
            status_text = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙"
            status_emoji = "🔥"
        elif "approved" in status_val:
            status_text = "𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙"
            status_emoji = "🟢"
        elif "declined" in status_val:
            status_text = "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙"
            status_emoji = "❌"
        else:
            status_text = "𝙀𝙧𝙧𝙤𝙧"
            status_emoji = "⚠️"
            
        # Format and return the final response
        return format_response(formatted_api_response, user_info, card_details, brand, issuer, country_name, country_flag, status_text, status_emoji)
    
    except Exception as e:
        logger.error(f"Error checking card: {e}")
        return f"⚠️ <b>Error checking card:</b> <code>{str(e)}</code>"
        

def format_response(api_response: str, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str,
                   status_text: str, status_emoji: str) -> str:
    """
    Format the API response into a beautiful message with emojis.
    
    Args:
        api_response: The formatted response string from the API
        user_info: Dictionary containing user information
        card_details: Full card details string
        brand: Card brand from BIN lookup
        issuer: Bank name from BIN lookup
        country_name: Country name from BIN lookup
        country_flag: Country emoji from BIN lookup
        status_text: The determined status text (e.g., "𝘿𝙚𝙘𝙡𝙞𝙣𝙚𝙙")
        status_emoji: The emoji for the status (e.g., "❌")
        
    Returns:
        Formatted string with emojis
    """
    
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
        credits_display = "Infinite😎"
    else:
        credits_display = str(user_credits)

    # Create user link with profile name hyperlinked
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with the exact structure requested
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{status_text}</b> {status_emoji}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒅</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Add credits info only if user has 0 credits and not unlimited
    credits_warning = ""
    if user_credits is not None and user_credits <= 0 and user_credits != float('inf'):
        credits_warning = f"\n<a href='https://t.me/failfr'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗦𝘁𝗿𝗶𝗽𝗲 0.50$</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{api_response}</code>
{bank_part}
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_st_command(update, context):
    """
    Handle the /st command.
    Updated cooldown logic: 
    - Trial users: 10 seconds gap.
    - Active plan users: No time limit (can run multiple concurrently).
    - Removed "wait for previous request" check to allow concurrency.
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Removed active_requests blocking logic to allow concurrent requests
    
    # Determine cooldown based on tier
    cooldown_seconds = 0
    if user_tier == "Trial":
        cooldown_seconds = 10
    # For active plans, cooldown remains 0
    
    # Check cooldown for Trial users (or specific tier logic)
    current_time = datetime.now()
    if cooldown_seconds > 0 and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=cooldown_seconds):
            remaining_seconds = cooldown_seconds - int(time_diff.total_seconds())
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
            "<i>Usage 1: /st card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /st</i>", 
            parse_mode="HTML"
        )
        return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # If user has no credits, don't process the card check
    if not has_credits:
        await update.message.reply_text(
            f"<a href='https://t.me/abtlnx'>⚠️</a> <b>𝙄𝙣𝙨𝙪𝙛𝙛𝙞𝙘𝙞𝙚𝙣𝙩 𝘾𝙧𝙚𝙙𝙞𝙩𝙨:</b>\n\n"
            f"<i>You have 0 credits left. Please recharge to continue using this service.</i>\n\n"
            f"<b>Current Tier:</b> <code>{user_tier}</code>",
            parse_mode="HTML"
        )
        return
    
    # Update the last command time immediately (before starting request)
    last_command_time[user_id] = current_time
    
    # Create a progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗦𝘁𝗿𝗶𝗽𝗲 0.50$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML")
    
    # Removed active_requests[user_id] = True
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
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
                        result = result + f"\n<a href='https://t.me/abtlnx'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            await checking_message.edit_text(result, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML")
        # Removed finally block for active_requests cleanup
    
    # Schedule the background task without awaiting it
    asyncio.create_task(background_check())

# Also add a handler for /stt command as an alias
async def handle_stt_command(update, context):
    """
    Handle the /stt command as an alias for /st.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Just call the st handler
    await handle_st_command(update, context)

if __name__ == "__main__":
    # For testing purposes
    test_card = "4553570612769104|04|2026|731"
    test_user = {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test"
    }
    asyncio.run(check_card(test_card, test_user))
