import re
import asyncio
import aiohttp
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.helpers import escape_markdown
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Set
import logging
import signal
import sys
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = "8001170085:AAFCUpgahwg8tfO0lVoT5I_dRd_Qa44iEQA"  # Replace with your bot token
RATE_LIMIT_SECONDS = 3  # Minimum seconds between requests per user
CACHE_DURATION_SECONDS = 300  # Cache duration for website analysis (5 minutes)
MAX_CONCURRENT_REQUESTS = 10  # Maximum concurrent requests to avoid flooding

# CMS patterns to detect different platforms
CMS_PATTERNS = {
    'Shopify': r'cdn\.shopify\.com|shopify\.js',
    'BigCommerce': r'cdn\.bigcommerce\.com|bigcommerce\.com',
    'Wix': r'static\.parastorage\.com|wix\.com',
    'Squarespace': r'static1\.squarespace\.com|squarespace-cdn\.com',
    'WooCommerce': r'wp-content/plugins/woocommerce/',
    'Magento': r'static/version\d+/frontend/|magento/',
    'PrestaShop': r'prestashop\.js|prestashop/',
    'OpenCart': r'catalog/view/theme|opencart/',
    'Shopify Plus': r'shopify-plus|cdn\.shopifycdn\.net/',
    'Salesforce Commerce Cloud': r'demandware\.edgesuite\.net/',
    'WordPress': r'wp-content|wp-includes/',
    'Joomla': r'media/jui|joomla\.js|joomla\.javascript/',
    'Drupal': r'sites/all/modules|drupal\.js/|sites/default/files|drupal\.settings\.js/',
    'TYPO3': r'typo3temp|typo3/',
    'Concrete5': r'concrete/js|concrete5/',
    'Umbraco': r'umbraco/|umbraco\.config/',
    'Sitecore': r'sitecore/content|sitecore\.js/',
    'Kentico': r'cms/getresource\.ashx|kentico\.js/',
    'Episerver': r'episerver/|episerver\.js/',
    'Custom CMS': r'(?:<meta name="generator" content="([^"]+)")'
}

# Security patterns to detect security measures
SECURITY_PATTERNS = {
    '3D Secure': r'3d_secure|threed_secure|secure_redirect',
}

# Payment gateways list
PAYMENT_GATEWAYS = [
    "PayPal", "Stripe", "Braintree", "Square", "Cybersource", "lemon-squeezy",
    "Authorize.Net", "2Checkout", "Adyen", "Worldpay", "SagePay",
    "Checkout.com", "Bolt", "Eway", "PayFlow", "Payeezy",
    "Paddle", "Mollie", "Viva Wallet", "Rocketgateway", "Rocketgate",
    "Rocket", "Auth.net", "Authnet", "rocketgate.com", "Recurly",
    "Shopify", "WooCommerce", "BigCommerce", "Magento", "Magento Payments",
    "OpenCart", "PrestaShop", "3DCart", "Ecwid", "Shift4Shop",
    "Shopware", "VirtueMart", "CS-Cart", "X-Cart", "LemonStand",
    "Convergepay", "PaySimple", "oceanpayments", "eProcessing",
    "hipay", "cybersourse", "payjunction", "usaepay", "creo",
    "SquareUp", "ebizcharge", "cpay", "Moneris", "cardknox",
    "matt sorra", "Chargify", "Paytrace", "hostedpayments", "securepay",
    "blackbaud", "LawPay", "clover", "cardconnect", "bluepay",
    "fluidpay", "Ebiz", "chasepaymentech", "Auruspay", "sagepayments",
    "paycomet", "geomerchant", "realexpayments", "Razorpay",
    "Apple Pay", "Google Pay", "Samsung Pay", "Cash App",
    "Revolut", "Zelle", "Alipay", "WeChat Pay", "PayPay", "Line Pay",
    "Skrill", "Neteller", "WebMoney", "Payoneer", "Paysafe",
    "Payeer", "GrabPay", "PayMaya", "MoMo", "TrueMoney",
    "Touch n Go", "GoPay", "JKOPay", "EasyPaisa",
    "Paytm", "UPI", "PayU", "PayUBiz", "PayUMoney", "CCAvenue",
    "Mercado Pago", "PagSeguro", "Yandex.Checkout", "PayFort", "MyFatoorah",
    "Kushki", "RuPay", "BharatPe", "Midtrans", "MOLPay",
    "iPay88", "KakaoPay", "Toss Payments", "NaverPay",
    "Bizum", "Culqi", "Pagar.me", "Rapyd", "PayKun", "Instamojo",
    "PhonePe", "BharatQR", "Freecharge", "Mobikwik", "BillDesk",
    "Citrus Pay", "RazorpayX", "Cashfree",
    "Klarna", "Affirm", "Afterpay",
    "Splitit", "Perpay", "Quadpay", "Laybuy", "Openpay",
    "Cashalo", "Hoolah", "Pine Labs", "ChargeAfter",
    "BitPay", "Coinbase Commerce", "CoinGate", "CoinPayments", "Crypto.com Pay",
    "BTCPay Server", "NOWPayments", "OpenNode", "Utrust", "MoonPay",
    "Binance Pay", "CoinsPaid", "BitGo", "Flexa",
    "ACI Worldwide", "Bank of America Merchant Services",
    "JP Morgan Payment Services", "Wells Fargo Payment Solutions",
    "Deutsche Bank Payments", "Barclaycard", "American Express Payment Gateway",
    "Discover Network", "UnionPay", "JCB Payment Gateway",
]

# Global variables for session management and rate limiting
session: aiohttp.ClientSession = None
user_last_request: Dict[int, datetime] = {}
domain_cache: Dict[str, Dict] = {}
concurrent_requests: Set[str] = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def init_session():
    global session
    if session is None or session.closed:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=50, force_close=True)
        session = aiohttp.ClientSession(timeout=timeout, connector=connector)

async def close_session():
    global session
    if session and not session.closed:
        await session.close()

# Fetch site content with rate limiting and caching
async def fetch_site(url: str):
    await init_session()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    domain = urlparse(url).netloc
    
    # Check cache first
    if domain in domain_cache:
        cache_entry = domain_cache[domain]
        if datetime.now() - cache_entry["timestamp"] < timedelta(seconds=CACHE_DURATION_SECONDS):
            logger.info(f"Using cached result for {domain}")
            return cache_entry["status"], cache_entry["html"], cache_entry["headers"]
    
    # Check if we're already fetching this domain
    if domain in concurrent_requests:
        logger.info(f"Already fetching {domain}, waiting...")
        while domain in concurrent_requests:
            await asyncio.sleep(0.5)
        # After waiting, check cache again
        if domain in domain_cache:
            cache_entry = domain_cache[domain]
            return cache_entry["status"], cache_entry["html"], cache_entry["headers"]
    
    # Add to concurrent requests
    concurrent_requests.add(domain)
    
    headers = {
        "authority": domain,
        "scheme": "https",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?1",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/140.0.0.0 Mobile Safari/537.36",
    }

    try:
        async with semaphore:
            async with session.get(url, headers=headers, timeout=15) as resp:
                text = await resp.text()
                status = resp.status
                resp_headers = dict(resp.headers)
                
                # Cache the result
                domain_cache[domain] = {
                    "status": status,
                    "html": text,
                    "headers": resp_headers,
                    "timestamp": datetime.now()
                }
                
                return status, text, resp_headers
    except asyncio.TimeoutError:
        logger.error(f"Timeout while fetching {url}")
        return None, None, None
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None, None, None
    finally:
        # Remove from concurrent requests
        concurrent_requests.discard(domain)

# Detect CMS platform
def detect_cms(html: str):
    for cms, pattern in CMS_PATTERNS.items():
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            if cms == 'Custom CMS':
                return match.group(1) or "Custom CMS"
            return cms
    return "Unknown"

# Detect security measures
def detect_security(html: str):
    patterns_3ds = [
        r'3d\s*secure',
        r'verified\s*by\s*visa',
        r'mastercard\s*securecode',
        r'3ds',
        r'3ds2',
        r'acsurl',
        r'pareq',
        r'three-domain-secure',
        r'secure_redirect',
    ]
    for pattern in patterns_3ds:
        if re.search(pattern, html, re.IGNORECASE):
            return "3D Secure Detected ✅"
    return "2D (No 3D Secure Found ❌)"

# Detect payment gateways
def detect_gateways(html: str):
    detected = []
    for gateway in PAYMENT_GATEWAYS:
        # Use word boundaries to avoid partial matches (e.g., "PayU" in "PayUmoney")
        pattern = r'\b' + re.escape(gateway) + r'\b'
        if re.search(pattern, html, re.IGNORECASE):
            detected.append(gateway)
    return ", ".join(detected) if detected else "None Detected"

# Detect captcha
def detect_captcha(html: str):
    html_lower = html.lower()
    if "hcaptcha" in html_lower:
        return "hCaptcha Detected ✅"
    elif "recaptcha" in html_lower or "g-recaptcha" in html_lower:
        return "reCAPTCHA Detected ✅"
    elif "captcha" in html_lower:
        return "Generic Captcha Detected ✅"
    return "No Captcha Detected"

# Detect Cloudflare
def detect_cloudflare(html: str, headers=None, status=None):
    if headers is None:
        headers = {}
    lower_keys = [k.lower() for k in headers.keys()]
    server = headers.get('Server', '').lower()
    # Check for Cloudflare presence (CDN or protection)
    cloudflare_indicators = [
        r'cloudflare',
        r'cf-ray',
        r'cf-cache-status',
        r'cf-browser-verification',
        r'__cfduid',
        r'cf_chl_',
        r'checking your browser',
        r'enable javascript and cookies',
        r'ray id',
        r'ddos protection by cloudflare',
    ]
    # Check headers for Cloudflare signatures
    if 'cf-ray' in lower_keys or 'cloudflare' in server or 'cf-cache-status' in lower_keys:
        # Parse HTML to check for verification/challenge page
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip().lower() if soup.title else ''
        challenge_indicators = [
            "just a moment",
            "attention required",
            "checking your browser",
            "enable javascript and cookies",
            "please wait while we verify",
        ]
        # Check for challenge page indicators
        if any(indicator in title for indicator in challenge_indicators):
            return "Cloudflare Verification Detected ✅"
        if any(re.search(pattern, html, re.IGNORECASE) for pattern in cloudflare_indicators):
            return "Cloudflare Verification Detected ✅"
        if status in (403, 503) and 'cloudflare' in html.lower():
            return "Cloudflare Verification Detected ✅"
        return "Cloudflare Present (No Verification) 🔍"
    return "None"

# Detect GraphQL
def detect_graphql(html: str):
    if re.search(r'/graphql|graphqlendpoint|apollo-client|query\s*\{|mutation\s*\{', html, re.IGNORECASE):
        return "GraphQL Detected ✅"
    return "No GraphQL Detected ❌"

# Format response with monospace text
def format_response(url: str, cms: str, security: str, gateways: str, 
                   captcha: str, cloudflare: str, graphql: str, 
                   status_code: int, headers: Dict) -> str:
    # Parse domain from URL
    domain = urlparse(url).netloc
    
    # Format the response
    response = f"""<pre><a href='https://t.me/abtlnx'>⩙</a> <b>𝑮𝒂𝒕𝒆 𝑪𝒉𝒆𝒄𝒌 𝑹𝒆𝒔𝒖𝒍𝒕𝒔</b></pre>
<a href='https://t.me/failfr'>⊀</a> <b>𝐔𝐑𝐋</b> ↬ <code>{domain}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐏𝐀𝐘𝐌𝐄𝐍𝐓𝐒</b> ↬ <code>{gateways}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐌𝐒</b> ↬ <code>{cms}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐒𝐓𝐀𝐓𝐔𝐒</b> ↬ <code>{status_code}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐒𝐄𝐂𝐔𝐑𝐈𝐓𝐘</b> ↬ <code>{security}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐀𝐏𝐓𝐂𝐇𝐀</b> ↬ <code>{captcha}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐂𝐋𝐎𝐔𝐃𝐅𝐋𝐀𝐑𝐄</b> ↬ <code>{cloudflare}</code>
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐑𝐀𝐏𝐇𝐐𝐋</b> ↬ <code>{graphql}</code>"""
    
    # Add dev link
    response += "\n<a href='https://t.me/abtlnx'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
    
    return response

# Check rate limit for a user
def check_rate_limit(user_id: int) -> bool:
    now = datetime.now()
    if user_id in user_last_request:
        time_diff = (now - user_last_request[user_id]).total_seconds()
        if time_diff < RATE_LIMIT_SECONDS:
            return False
    user_last_request[user_id] = now
    return True

# Main command handler
async def handle_gate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /gate command to analyze a website.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Check rate limit
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text(
            f"⚠️ <b>Rate limit exceeded!</b>\n\n"
            f"<i>Please wait {RATE_LIMIT_SECONDS} seconds between requests.</i>",
            parse_mode="HTML"
        )
        return
    
    # Get the URL from command
    if not context.args:
        await update.message.reply_text(
            "⚠️ <b>Missing URL!</b>\n\n"
            "<i>Usage: /gate [url]</i>\n\n"
            "<i>Example: /gate example.com</i>",
            parse_mode="HTML"
        )
        return
    
    url = context.args[0]
    
    # Auto-add https if not present
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝘀𝒕𝒕𝘀...</b></pre>\n"
        f"<a href='https://t.me/failfr'>⊀</a> <b>𝐔𝐑𝐋</b> ↬ <code>{url}</code>",
        parse_mode="HTML"
    )
    
    try:
        # Fetch the site
        status_code, html, headers = await fetch_site(url)
        
        if status_code is None:
            # Failed to fetch
            await processing_message.edit_text(
                "⚠️ <b>Error:</b> <code>Failed to fetch the site</code>\n\n"
                "<i>Please check the URL and try again.</i>",
                parse_mode="HTML"
            )
            return
        
        # Parse the HTML
        soup = BeautifulSoup(html, 'html.parser')
        
        # Detect various aspects
        cms = detect_cms(html)
        security = detect_security(html)
        gateways = detect_gateways(html)
        captcha = detect_captcha(html)
        cloudflare = detect_cloudflare(html, headers, status_code)
        graphql = detect_graphql(html)
        
        # Format and send the response
        response = format_response(
            url, cms, security, gateways, 
            captcha, cloudflare, graphql, 
            status_code, headers
        )
        
        await processing_message.edit_text(response, parse_mode="HTML")
    
    except Exception as e:
        logger.error(f"Error in gate command: {e}")
        await processing_message.edit_text(
            f"⚠️ <b>Error:</b> <code>{str(e)}</code>\n\n"
            "<i>Please try again later.</i>",
            parse_mode="HTML"
        )

# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f'Exception while handling an update: {context.error}')
    
    # Try to inform the user about the error
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text(
                "⚠️ <b>An error occurred!</b>\n\n"
                "<i>Please try again later.</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass  # Ignore errors in error handler

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    asyncio.create_task(close_session())
    sys.exit(0)

# Main function to run the bot
def main():
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handler
    application.add_handler(CommandHandler("gate", handle_gate_command))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
