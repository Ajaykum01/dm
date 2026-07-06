import logging
import aiohttp
import asyncio
import io
import time
import re
import json
from typing import List, Dict, Tuple, Callable, Optional
from telegram import Update, Document, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler

# Configure logging
logger = logging.getLogger(__name__)

# API endpoint for testing sites
API_BASE_URL = "http://autosh.nikhilkhokhar.com/index.php"

# Test card for site validation
TEST_CARD = "4910149950579116|03|28|106"

# Dictionary to track pending validations waiting for price selection
PENDING_VALIDATIONS = {}

# Dictionary to track active processes per user
active_processes = {}

# Database functions for user sites
def get_user_sites(user_id: int) -> List[str]:
    """
    Get list of sites for a user from database.
    
    Args:
        user_id: ID of the user
        
    Returns:
        List of site URLs
    """
    try:
        import sqlite3
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            user_id INTEGER,
            site_url TEXT,
            PRIMARY KEY (user_id, site_url)
        )
        ''')
        
        # Get user sites
        cursor.execute('SELECT site_url FROM user_sites WHERE user_id = ?', (user_id,))
        sites = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return sites
    except Exception as e:
        logger.error(f"Error getting user sites: {str(e)}")
        return []

def add_user_site(user_id: int, site_url: str) -> bool:
    """
    Add a site to the user's list of sites.
    
    Args:
        user_id: ID of the user
        site_url: URL of the site to add
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import sqlite3
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            user_id INTEGER,
            site_url TEXT,
            PRIMARY KEY (user_id, site_url)
        )
        ''')
        
        # Insert the site
        cursor.execute('INSERT OR IGNORE INTO user_sites (user_id, site_url) VALUES (?, ?)', 
                       (user_id, site_url))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error adding user site: {str(e)}")
        return False

def add_working_sites(user_id: int, working_sites: List[str]) -> bool:
    """
    Add multiple working sites to the user's list.
    
    Args:
        user_id: ID of the user
        working_sites: List of working site URLs
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import sqlite3
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Create table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            user_id INTEGER,
            site_url TEXT,
            PRIMARY KEY (user_id, site_url)
        )
        ''')
        
        # Insert all working sites
        for site_url in working_sites:
            cursor.execute('INSERT OR IGNORE INTO user_sites (user_id, site_url) VALUES (?, ?)', 
                           (user_id, site_url))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error adding working sites: {str(e)}")
        return False

def remove_user_site(user_id: int, site_url: str) -> bool:
    """
    Remove a site from the user's list of sites.
    
    Args:
        user_id: ID of the user
        site_url: URL of the site to remove
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import sqlite3
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Delete the site
        cursor.execute('DELETE FROM user_sites WHERE user_id = ? AND site_url = ?', 
                       (user_id, site_url))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error removing user site: {str(e)}")
        return False

def remove_all_user_sites(user_id: int) -> bool:
    """
    Remove all sites from the user's list.
    
    Args:
        user_id: ID of the user
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import sqlite3
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        
        # Delete all sites for the user
        cursor.execute('DELETE FROM user_sites WHERE user_id = ?', (user_id,))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error removing all user sites: {str(e)}")
        return False

def extract_domain_from_url(url: str) -> str:
    """
    Extract just the domain (with https://) from a full URL.
    
    Args:
        url: Full URL
        
    Returns:
        Domain with https:// prefix
    """
    # Ensure URL uses HTTPS
    if url.startswith('http://'):
        url = url.replace('http://', 'https://', 1)
    elif not url.startswith('https://'):
        url = 'https://' + url
    
    # Extract domain using regex
    domain_match = re.match(r'(https://[^/]+)', url)
    if domain_match:
        return domain_match.group(1)
    
    # Fallback to returning the URL with HTTPS
    return url

# Hardcoded proxies for rotation
HARDCODED_PROXIES = [
    "http://0A2JelrNEymAcMsT:cHo1x72JjZPwB0lg@geo.g-w.info:10080",
    "http://g7GxaNTU0FzL14da:xzE9IpVCdvZ1uhtz@geo.g-w.info:10080",
    "http://rw38SdWb8zuPdfWl:4nC2GX9y4cjWOa7Y@geo.g-w.info:10080",
    "http://TnReJ3edUaeYfYLu:b7hgKKZt5nVWP965@geo.g-w.info:10080"
]

# Error messages that indicate a site is not working
RETRY_ERRORS = [
    'r4 token empty',
    'risky',
    'item is not in cart',
    'product not found',    
    'hcaptcha detected',
    'tax ammount empty',
    'Error in 1 req: OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to',
    'del ammount empty',
    'product id is empty',
    'Error in 1 req: Could not resolve host:',
    'py id empty',
    'clinte token',
    'HCAPTCHA_DETECTED',
    'RECEIPT_EMPTY',
    'NA',
    'r2 id empty',
    'Site requires login!',
    'Failed to get token',
    'No Valid Products',
    'Not Shopify!',
    'AMOUNT_TOO_SMALL',
    'Captcha at Checkout - Use good proxies!',
    'Payment method is not shopify!',
    'Site not supported for now!',
    'Connection error',
    'error',
    'receipt_empty',
    'amount_too_small',
    'HCAPTCHA_DETECTED',
    'Token Not Found',
    'INVALID_RESPONSE',
    # Added specific payment gateways to reject
    'authorize.net',
    'ONERWAY (Direct)'
]

# cURL errors that should trigger a retry with proxy rotation
CURL_ERRORS = [
    'cURL error: Recv failure: Connection reset by peer',
    'cURL error: OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to',
    'cURL error: CONNECT tunnel failed, response 500',
    'cURL error: Proxy CONNECT aborted',
    'cURL error:'
]

def is_curl_error(response_text: str) -> bool:
    """
    Check if the response text contains a cURL error that should trigger a retry.
    
    Args:
        response_text: Response text from the API
        
    Returns:
        True if it's a cURL error that should trigger a retry, False otherwise
    """
    for error in CURL_ERRORS:
        if error in response_text:
            return True
    return False

def has_restricted_gateway(response_text: str) -> bool:
    """
    Check if the response text indicates a restricted payment gateway.
    
    Args:
        response_text: Response text from the API
        
    Returns:
        True if the gateway is restricted, False otherwise
    """
    # Check for authorize.net
    if 'authorize.net' in response_text.lower():
        return True
    
    # Check for ONERWAY (Direct)
    if 'onerway' in response_text.lower() and 'direct' in response_text.lower():
        return True
    
    return False

async def test_site(site_url: str, user_id: int, proxy_index: int = 0, retry_count: int = 0) -> Tuple[bool, str, str]:
    """
    Test a single site with a test card.
    
    Args:
        site_url: URL of the site to test
        user_id: ID of the user (for getting proxies)
        proxy_index: Index of the proxy to use
        retry_count: Number of retries already attempted
        
    Returns:
        Tuple of (is_working, response_text, price)
    """
    try:
        # Extract domain from URL
        domain = extract_domain_from_url(site_url)
        
        # Get proxy for this request from hardcoded list
        proxy = HARDCODED_PROXIES[proxy_index % len(HARDCODED_PROXIES)]
        # Remove http:// from proxy if present
        if proxy.startswith("http://"):
            proxy = proxy[7:]
        
        # Prepare API URL with query parameters
        api_url = f"{API_BASE_URL}?site={domain}&cc={TEST_CARD}&proxy={proxy}"
        
        # Use aiohttp for async HTTP request with extended timeout of 60 seconds
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url) as response:
                if response.status >= 500:
                    return False, f"Server error: {response.status}", ""
                
                api_response = await response.json()
                response_text = api_response.get("Response", "")
                price = api_response.get("Price", "")
                gateway = api_response.get("Gateway", "")
                
                # Convert price to float for comparison
                price_value = 0
                if price:
                    try:
                        # Remove currency symbols and convert to float
                        price_clean = re.sub(r'[^\d.]', '', price)
                        price_value = float(price_clean)
                    except (ValueError, TypeError):
                        price_value = 0
                
                # Check if price is higher than $40, mark as dead if so
                if price_value > 40:
                    return False, f"Price too high: ${price_value}", price
                
                # Check for restricted payment gateways (authorize.net or ONERWAY (Direct))
                if gateway and (
                    'authorize.net' in gateway.lower() or 
                    ('onerway' in gateway.lower() and 'direct' in gateway.lower())
                ):
                    logger.info(f"Site {site_url} uses restricted payment gateway: {gateway}")
                    return False, f"Restricted gateway: {gateway}", price
                
                # Check if response contains any error that indicates a dead site
                response_text_lower = response_text.lower()
                for error in RETRY_ERRORS:
                    if error.lower() in response_text_lower:
                        return False, response_text, price
                
                # Check if it's a cURL error and we should retry
                if is_curl_error(response_text) and retry_count < 3:
                    # Try with a different proxy
                    new_proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)
                    logger.info(f"Retrying {site_url} with proxy {HARDCODED_PROXIES[new_proxy_index]} (attempt {retry_count + 1})")
                    return await test_site(site_url, user_id, new_proxy_index, retry_count + 1)
                
                # If we get here, the site is working
                return True, response_text, price
    
    except asyncio.TimeoutError:
        logger.info(f"Timeout testing {site_url} with proxy {proxy}")
        # Retry with a different proxy if we haven't reached max retries
        if retry_count < 3:
            new_proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)
            logger.info(f"Retrying {site_url} with different proxy due to timeout (attempt {retry_count + 1})")
            return await test_site(site_url, user_id, new_proxy_index, retry_count + 1)
        
        return False, "Timeout", ""
    except aiohttp.ClientError as e:
        logger.info(f"Connection error testing {site_url} with proxy {proxy}: {str(e)}")
        # Retry with a different proxy if we haven't reached max retries
        if retry_count < 3:
            new_proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)
            logger.info(f"Retrying {site_url} with different proxy due to connection error (attempt {retry_count + 1})")
            return await test_site(site_url, user_id, new_proxy_index, retry_count + 1)
        
        return False, f"Connection error: {str(e)}", ""
    except ValueError as e:
        logger.info(f"JSON decode error testing {site_url}: {str(e)}")
        return False, f"JSON decode error: {str(e)}", ""
    except Exception as e:
        logger.error(f"Unexpected error testing site {site_url}: {str(e)}")
        return False, f"Unexpected error: {str(e)}", ""
        
async def test_sites_batch(
    sites: List[str], 
    user_id: int, 
    progress_callback=None,
    working_site_callback: Optional[Callable[[str, str], None]] = None
) -> Dict[str, Tuple[bool, str, str]]:
    """
    Test a batch of sites and return results.
    
    Args:
        sites: List of site URLs to test
        user_id: ID of the user (for getting proxies)
        progress_callback: Optional callback function to update progress
        working_site_callback: Optional callback function to handle working sites immediately
        
    Returns:
        Dictionary with site URLs as keys and (is_working, response_text, price) as values
    """
    results = {}
    total_sites = len(sites)
    tested_sites = 0
    working_sites = 0
    dead_sites = 0
    
    # Create a semaphore to limit concurrent requests (reduced to 3 to avoid timeouts)
    semaphore = asyncio.Semaphore(15)
    
    # Track which proxy index to use for each site
    proxy_index = 0
    
    async def test_with_semaphore(site_url):
        nonlocal tested_sites, working_sites, dead_sites, proxy_index
        async with semaphore:
            # Use a different proxy for each site based on current index
            current_proxy_index = proxy_index
            proxy_index = (proxy_index + 1) % len(HARDCODED_PROXIES)  # Increment for next site
            
            result = await test_site(site_url, user_id, current_proxy_index)
            tested_sites += 1
            
            # Update counters
            if result[0]:  # is_working
                working_sites += 1
                # Immediately handle working site if callback provided
                if working_site_callback:
                    try:
                        domain = extract_domain_from_url(site_url)
                        # Call the callback with the domain and price
                        await working_site_callback(domain, result[2])
                        logger.info(f"Processed working site {domain} with callback")
                    except Exception as e:
                        logger.error(f"Error in working_site_callback: {str(e)}")
            else:
                dead_sites += 1
            
            # Update progress if callback provided (every 50 sites or when all done)
            if progress_callback and (tested_sites % 20 == 0 or tested_sites == total_sites):
                await progress_callback(tested_sites, total_sites, working_sites, dead_sites)
            
            return site_url, result
    
    # Create tasks for all sites
    tasks = [asyncio.create_task(test_with_semaphore(site_url)) for site_url in sites]
    
    # Process results as they complete
    for task in asyncio.as_completed(tasks):
        try:
            site_url, (is_working, response_text, price) = await task
            results[site_url] = (is_working, response_text, price)
            logger.info(f"Tested site {site_url}: {'Working' if is_working else 'Not working'}")
        except Exception as e:
            logger.error(f"Error processing task result: {str(e)}")
            # Continue processing other tasks even if one fails
    
    return results

async def create_sites_report(test_results: Dict[str, Tuple[bool, str, str]]) -> io.BytesIO:
    """
    Create a text file with site test results in the requested format.
    
    Args:
        test_results: Dictionary with site URLs as keys and (is_working, response_text, price) as values
        
    Returns:
        BytesIO object containing the report
    """
    # Count working sites
    working_count = sum(1 for _, (is_working, _, _) in test_results.items() if is_working)
    
    # Create report content in the requested format
    report_content = f"Total working Sites - {working_count}\n"
    report_content += "═════════════════════════════\n"
    
    # Add working sites with their prices
    for site_url, (is_working, response_text, price) in test_results.items():
        if is_working:
            # Extract domain for the report
            domain = extract_domain_from_url(site_url)
            price_str = f" (${price})" if price else ""
            # Fix: Add curly braces around response text and proper spacing
            report_content += f"{domain}  {{{response_text}}}  {price_str}\n"
    
    # Create BytesIO object with new file name
    report_bytes = io.BytesIO(report_content.encode('utf-8'))
    report_bytes.name = "CARDXCHK_workingsites.txt"
    
    return report_bytes

async def update_progress_message(context, chat_id, message_id, tested, total, working, dead):
    """
    Update the progress message with working/dead sites progress.
    
    Args:
        context: Telegram context object
        chat_id: Chat ID to update
        message_id: Message ID to update
        tested: Number of sites tested
        total: Total number of sites
        working: Number of working sites found
        dead: Number of dead sites found
    """
    try:
        # Calculate percentage
        percentage = int((tested / total) * 100) if total > 0 else 0
        
        # Format progress message with custom UI showing working/dead progress
        progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 📊</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Site Validation
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{total}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐞𝐬𝐭𝐞𝐝 ↬ <code>{tested}/{total} ({percentage}%)</code>
<a href='https://t.me/failfr'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{working}</code>
<a href='https://t.me/failfr'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>{dead}</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=progress_msg,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error updating progress message: {str(e)}")

def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract all URLs from a text using regex and ensure they use HTTPS.
    
    Args:
        text: Text to extract URLs from
        
    Returns:
        List of HTTPS URLs found in the text
    """
    # Regex pattern to match URLs
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
    urls = re.findall(url_pattern, text)
    
    # Clean up URLs and ensure HTTPS
    cleaned_urls = []
    for url in urls:
        # Remove trailing punctuation
        url = url.rstrip('.,;:!?)')
        
        # Convert to HTTPS if not already
        if url.startswith('http://'):
            url = url.replace('http://', 'https://', 1)
        elif not url.startswith('https://'):
            url = 'https://' + url
        
        # Ensure it's a valid URL
        if url.startswith('https://'):
            cleaned_urls.append(url)
    
    return cleaned_urls

async def _process_seturl_sites(update: Update, context: CallbackContext, sites_to_test: List[str], process_id: str, max_price: int):
    """
    Background task to process sites for /seturl command.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        sites_to_test: List of site URLs to test
        process_id: Unique ID for this process
        max_price: Maximum price to add site to DB
    """
    user_id = update.effective_user.id
    
    # Determine if this is a group chat
    is_group = update.message.chat.type in ['group', 'supergroup']
    
    # Create a progress callback function
    async def progress_callback(tested, total, working, dead):
        try:
            # Get the status message for this specific process
            if process_id in active_processes and "status_message" in active_processes[process_id]:
                await update_progress_message(
                    context, 
                    update.message.chat_id, 
                    active_processes[process_id]["status_message"].message_id, 
                    tested, 
                    total,
                    working,
                    dead
                )
        except Exception as e:
            logger.error(f"Error in progress callback: {str(e)}")
    
    # Create a set to track sites that were added to DB (based on price filter)
    added_sites_count = 0
    
    # Create a callback function to immediately add working sites to the database
    async def add_working_site_to_db(domain: str, price: str):
        nonlocal added_sites_count
        try:
            # Parse price to float
            current_price = 0
            if price:
                try:
                    price_clean = re.sub(r'[^\d.]', '', price)
                    current_price = float(price_clean)
                except ValueError:
                    current_price = 0
            
            # Only add if price is within the selected range
            if current_price <= max_price:
                if add_user_site(user_id, domain):
                    added_sites_count += 1
                    logger.info(f"Added site {domain} (Price: ${current_price}) to database")
            else:
                logger.info(f"Skipped site {domain} (Price: ${current_price}) - Exceeds max price ${max_price}")
                
        except Exception as e:
            logger.error(f"Error in working site callback for {domain}: {str(e)}")
    
    # Test all sites with both progress callback and working site callback
    test_results = await test_sites_batch(
        sites_to_test, 
        user_id, 
        progress_callback, 
        working_site_callback=add_working_site_to_db
    )
    
    # Extract working sites for report (regardless of price, report shows all found)
    working_sites = []
    
    for site_url, (is_working, response_text, price) in test_results.items():
        if is_working:
            domain = extract_domain_from_url(site_url)
            working_sites.append((domain, price))
    
    # Create report
    report_file = await create_sites_report(test_results)
    
    # Send report to user (DM or group based on chat type)
    try:
        # FIX: Replaced unsafe symbols in links and escaped <=
        caption_text = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙑𝙖𝙡𝙞𝙙𝙖𝙩𝙞𝙤𝙣 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚 ✅</pre>
<a href="https://t.me/failfr">⊀</a> ✅ 𝐓𝐨𝐭𝚊𝐥 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{len(working_sites)}/{len(sites_to_test)}</code>
<a href="https://t.me/failfr">⊀</a> 💾 𝐀𝐝𝐝𝐞𝐝 𝐓𝐨 𝐃𝐁 (0-${max_price}) ↬ <code>{added_sites_count}</code>
<a href="https://t.me/failfr">⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>{len(sites_to_test) - len(working_sites)}/{len(sites_to_test)}</code>

<i>Only working sites with price &lt;= ${max_price} have been added to your account.</i>
<a href="https://t.me/failfr">⊀</a> 𝐃𝐞𝐯 ↬ <a href="https://t.me/failurefr_07">kคli liຖนxx</a>"""

        if is_group:
            # Send to group chat
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=report_file,
                caption=caption_text,
                parse_mode="HTML"
            )
        else:
            # Send to user's DM
            await context.bot.send_document(
                chat_id=user_id,
                document=report_file,
                caption=caption_text,
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error sending report to user {user_id}: {str(e)}")
        error_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href="https://t.me/abtlnx">⊀</a> 𝐄𝐫𝐫𝐨𝐫 ↬ <code>{str(e)}</code>

<i>Failed to send validation report. Please try again.</i>
<a href="https://t.me/abtlnx">⌬</a> 𝐃𝐞𝐯 ↬ <a href="https://t.me/failurefr_07">kคli liຖนxx</a>"""
        
        # FIX: Use direct context.bot.send_message to avoid MiniUpdate reply_text crash
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=error_msg,
            parse_mode="HTML"
        )
    
    # Delete status message
    try:
        if process_id in active_processes and "status_message" in active_processes[process_id]:
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=active_processes[process_id]["status_message"].message_id
            )
            # Remove the process from active_processes
            del active_processes[process_id]
    except Exception as e:
        logger.error(f"Error deleting status message: {str(e)}")
        
async def handle_seturl_command(update: Update, context: CallbackContext):
    """
    Handle the /seturl command for adding user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Set URL command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    from plans import get_user_current_tier
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial":
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Set URL command denied for trial user {user_id}")
        return
    
    # Check if user provided a URL or a file
    sites_to_test = []
    
    # Check if a document was provided
    if update.message.document and update.message.document.mime_type == "text/plain":
        # Download the file
        file = await context.bot.get_file(update.message.document.file_id)
        file_content = await file.download_as_bytearray()
        text = file_content.decode('utf-8')
        
        # Extract URLs from the text
        sites_to_test = extract_urls_from_text(text)
        logger.info(f"Loaded {len(sites_to_test)} sites from file for user {user_id}")
    # Check if sites were provided as text (after the command)
    elif context.args:
        # Get the message text directly to preserve newlines
        message_text = update.message.text
        
        # Remove the command and any leading/trailing whitespace
        if message_text.startswith('/seturl'):
            message_text = message_text[8:].strip()
        
        # Extract URLs from the text
        sites_to_test = extract_urls_from_text(message_text)
        logger.info(f"Loaded {len(sites_to_test)} sites from message for user {user_id}")
    # Check if there's a reply to a message with sites
    elif update.message.reply_to_message:
        # Check if the replied message has text
        if update.message.reply_to_message.text:
            # Get the text from the replied message
            reply_text = update.message.reply_to_message.text
            sites_to_test = extract_urls_from_text(reply_text)
            logger.info(f"Loaded {len(sites_to_test)} sites from reply for user {user_id}")
        # Check if the replied message has a document
        elif update.message.reply_to_message.document and update.message.reply_to_message.document.mime_type == "text/plain":
            # Download the file
            file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
            file_content = await file.download_as_bytearray()
            text = file_content.decode('utf-8')
            
            # Extract URLs from the text
            sites_to_test = extract_urls_from_text(text)
            logger.info(f"Loaded {len(sites_to_test)} sites from replied file for user {user_id}")
    
    # If no sites provided, show the user's current sites
    if not sites_to_test:
        user_sites = get_user_sites(user_id)
        
        if user_sites:
            # Show only the first 3 sites as examples
            example_sites = user_sites[:3]
            sites_list = "\n".join([f"• <code>{site}</code>" for site in example_sites])
            
            if len(user_sites) > 3:
                sites_list += f"\n• <code>... and {len(user_sites) - 3} more</code>"
            
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙔𝙤𝙪𝙧 𝙎𝙞𝙩𝙚𝙨 📋</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(user_sites)}</code>

<b>Example sites:</b>
{sites_list}

<b>To add new sites:</b> <code>/seturl https://example.myshopify.com</code>
<b>To remove a site:</b> <code>/delurl https://example.myshopify.com</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failedfr'>kคli liຖนxx</a>"""
        else:
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙉𝙤 𝙎𝙞𝙩𝙚𝙨 ⚠️</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>You don't have any sites configured.</i>

<b>To add sites:</b> <code>/seturl https://example.myshopify.com</code>
<i>Please add at least one site before using the /msh command.</i>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
        
        await update.message.reply_text(message, parse_mode="HTML")
        return
    
    # Store sites in pending validations
    PENDING_VALIDATIONS[user_id] = sites_to_test
    
    # Create keyboard for price selection
    keyboard = [
        [
            InlineKeyboardButton("0-5 USD", callback_data=f"seturl_price_5"),
            InlineKeyboardButton("0-10 USD", callback_data=f"seturl_price_10")
        ],
        [
            InlineKeyboardButton("0-20 USD", callback_data=f"seturl_price_20"),
            InlineKeyboardButton("0-40 USD", callback_data=f"seturl_price_40")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙚𝙡𝙚𝙘𝙩 𝙍𝙖𝙣𝙜𝙚 💲</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(sites_to_test)}</code>
<i>Select the price range you want to add sites:</i>""",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def handle_seturl_price_callback(update: Update, context: CallbackContext):
    """
    Handle the callback from the price range selection.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    
    # Determine max price from callback data
    max_price = 0
    if "seturl_price_5" in callback_data:
        max_price = 5
    elif "seturl_price_10" in callback_data:
        max_price = 10
    elif "seturl_price_20" in callback_data:
        max_price = 20
    elif "seturl_price_40" in callback_data:
        max_price = 40
    else:
        await query.edit_message_text("Invalid selection.")
        return
    
    # Check if user has pending sites
    if user_id not in PENDING_VALIDATIONS:
        await query.edit_message_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<i>No sites found or session expired. Please use /seturl again.</i>""",
            parse_mode="HTML"
        )
        return
    
    sites_to_test = PENDING_VALIDATIONS.pop(user_id)
    
    # Generate a unique process ID for this command
    process_id = f"{user_id}_{int(time.time())}"
    
    # Update the callback query message to initial progress
    progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 📊</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Site Validation (Max: ${max_price})
<a href='https://t.me/abtlnx'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(sites_to_test)}</code>
<a href='https://t.me/abtlnx'>⊀</a> 𝐓𝐞𝐬𝐭𝐞𝐝 ↬ <code>0/{len(sites_to_test)} (0%)</code>
<a href='https://t.me/abtlnx'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>0</code>
<a href='https://t.me/abtlnx'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>0</code>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    try:
        # Edit the message instead of deleting and creating new one to keep flow smooth
        status_message = await query.edit_message_text(
            progress_msg,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error editing message to progress: {e}")
        # Fallback: send new message if edit fails
        status_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=progress_msg,
            parse_mode="HTML"
        )
        
    # Store the process information in the active_processes dictionary
    active_processes[process_id] = {
        "status_message": status_message,
        "user_id": user_id
    }
    
    # Create a mock update object that has all necessary attributes for _process_seturl_sites
    class MiniUpdate:
        def __init__(self, chat_id, user_id, chat_type, ctx):
            self.effective_user = type('obj', (object,), {'id': user_id})()
            
            # Define a fake message object that supports reply_text
            async def mock_reply_text(text, parse_mode=None):
                await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            
            self.message = type('obj', (object,), {
                'chat_id': chat_id,
                'chat': type('obj', (object,), {'type': chat_type})(),
                'reply_text': mock_reply_text
            })()

    # Use the chat from the callback query message
    chat_type = query.message.chat.type
    fake_update = MiniUpdate(query.message.chat_id, user_id, chat_type, context)

    # Process sites in background
    asyncio.create_task(_process_seturl_sites(fake_update, context, sites_to_test, process_id, max_price))
async def handle_delurl_command(update: Update, context: CallbackContext):
    """
    Handle the /delurl command for removing user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Delete URL command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    from plans import get_user_current_tier
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial":
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Delete URL command denied for trial user {user_id}")
        return
    
    # Check if user provided a URL
    if not context.args:
        message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙍𝙚𝙢𝙤𝙫𝙚 𝙎𝙞𝙩𝙚 🗑️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐄𝐱𝐚𝐦𝐩𝐥𝐞 ↬ <code>/delurl https://example.myshopify.com</code>

<b>To remove all sites:</b> <code>/delall</code>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>"""
        
        await update.message.reply_text(message, parse_mode="HTML")
        return
    
    # Get URL from command arguments
    site_url = context.args[0]
    
    # Extract domain from URL
    domain = extract_domain_from_url(site_url)
    
    # Check if site exists in user's list
    user_sites = get_user_sites(user_id)
    if domain not in user_sites:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Site not found in your list!</i>

<i>This site is not in your list of sites.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failedfr'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        return
    
    # Remove site from user's list
    if remove_user_site(user_id, domain):
        # Get updated list of sites
        user_sites = get_user_sites(user_id)
        
        if user_sites:
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙪𝘾𝙘𝙚𝙨𝙨 ✅</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Site removed successfully!</i>

<a href='https://t.me/failfr'>⊀</a> 𝐑𝐞𝐦𝚊𝐢𝐧𝐢𝐧𝐠 ↬ <code>{len(user_sites)} sites</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failfr'>kคli liຖนxx</a>"""
        else:
            message = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙪𝘾𝙘𝙚𝙨𝙨 ✅</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Site removed successfully!</i>

<i>You don't have any sites configured. Please add at least one site using /seturl command.</i>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
        
        await update.message.reply_text(message, parse_mode="HTML")
        logger.info(f"User {user_id} removed site: {domain}")
    else:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Failed to remove site!</i>

<i>Please try again later.</i>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failfr'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        logger.error(f"Failed to remove site {domain} for user {user_id}")

async def handle_delall_command(update: Update, context: CallbackContext):
    """
    Handle the /delall command for removing all user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Delete all command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    from plans import get_user_current_tier
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial":
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Delete all command denied for trial user {user_id}")
        return
    
    # Get user's current sites
    user_sites = get_user_sites(user_id)
    
    if not user_sites:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙉𝙤 𝙎𝙞𝙩𝙚𝙨 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>You don't have any sites configured.</i>

<i>There are no sites to remove.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        return
    
    # Create confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, delete all", callback_data=f"delall_confirm_{user_id}"),
            InlineKeyboardButton("❌ No, cancel", callback_data="delall_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘾𝙤𝙣𝙛𝙞𝙧𝙢 𝘾𝙚𝙡𝙚𝙩𝙞𝙤𝙣 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Are you sure you want to delete all {len(user_sites)} sites?</i>

<i>This action cannot be undone.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>""",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

async def _process_resites_sites(update: Update, context: CallbackContext, process_id: str):
    """
    Background task to process sites for /resites command.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        process_id: Unique ID for this process
    """
    user_id = update.effective_user.id
    
    # Get user's current sites
    user_sites = get_user_sites(user_id)
    
    # Determine if this is a group chat
    is_group = update.message.chat.type in ['group', 'supergroup']
    
    # Create a progress callback function
    async def progress_callback(tested, total, working, dead):
        try:
            # Get the status message for this specific process
            if process_id in active_processes and "status_message" in active_processes[process_id]:
                await update_progress_message(
                    context, 
                    update.message.chat_id, 
                    active_processes[process_id]["status_message"].message_id, 
                    tested, 
                    total,
                    working,
                    dead
                )
        except Exception as e:
            logger.error(f"Error in progress callback: {str(e)}")
    
    # Create a set to track sites that were already in the database
    existing_sites = set(user_sites)
    
    # Create a set to track working sites
    working_sites_set = set()
    
    # Create a callback function to immediately add working sites to the database
    async def add_working_site_to_db(domain: str, price: str):
        try:
            # Add the working site to our tracking set
            working_sites_set.add(domain)
            
            # The site was already in the database (we're just revalidating),
            # so we don't need to add it again yet
            logger.info(f"Marked site {domain} as working")
        except Exception as e:
            logger.error(f"Error in working site callback for {domain}: {str(e)}")
    
    # Test all sites with both progress callback and working site callback
    test_results = await test_sites_batch(
        user_sites, 
        user_id, 
        progress_callback,
        working_site_callback=add_working_site_to_db
    )
    
    # Remove all sites first
    remove_all_user_sites(user_id)
    
    # Add only working sites back to database
    if working_sites_set:
        add_working_sites(user_id, list(working_sites_set))
        logger.info(f"Re-added {len(working_sites_set)} working sites to database")
    
    # Extract working sites with their prices for report
    working_sites = []
    
    for site_url, (is_working, response_text, price) in test_results.items():
        if is_working:
            domain = extract_domain_from_url(site_url)
            working_sites.append((domain, price))
    
    # Create report
    report_file = await create_sites_report(test_results)
    
    # Send report to user (DM or group based on chat type)
    try:
        if is_group:
            # Send to group chat
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=report_file,
                caption=f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙍𝚎𝙫𝚊𝙡𝙞𝙙𝚊𝙩𝙞𝙤𝙣 𝘾𝙤𝙢𝙥𝙡𝚎𝙩𝚎 ✅</pre>
<a href='https://t.me/failfr'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{len(working_sites)}/{len(user_sites)}</code>
<a href='https://t.me/failfr'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 𝐑𝐞𝐦𝐨𝐯𝐞𝐝 ↬ <code>{len(user_sites) - len(working_sites)}/{len(user_sites)}</code>

<i>Only working sites (with prices between $0-$40) have been kept in your account.</i>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failfr'>kคli liຖนxx</a>""",
                parse_mode="HTML"
            )
        else:
            # Send to user's DM
            await context.bot.send_document(
                chat_id=user_id,
                document=report_file,
                caption=f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙍𝚎𝙫𝚊𝙡𝙞𝙙𝚊𝙩𝙞𝙤𝙣 𝘾𝙤𝙢𝙥𝙡𝚎𝙩𝚎 ✅</pre>
<a href='https://t.me/failfr'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>{len(working_sites)}/{len(user_sites)}</code>
<a href='https://t.me/failfr'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 𝐑𝐞𝐦𝐨𝐯𝐞𝐝 ↬ <code>{len(user_sites) - len(working_sites)}/{len(user_sites)}</code>

<i>Only working sites (with prices between $0-$40) have been kept in your account.</i>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Error sending report to user {user_id}: {str(e)}")
        if is_group:
            await update.message.reply_text(
                f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 ↬ <code>{str(e)}</code>

<i>Failed to send revalidation report. Please try again.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>""",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐄𝐫𝐫𝐨𝐫 ↬ <code>{str(e)}</code>

<i>Failed to send revalidation report. Please try again.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>""",
                parse_mode="HTML"
            )
    
    # Delete status message
    try:
        if process_id in active_processes and "status_message" in active_processes[process_id]:
            await context.bot.delete_message(
                chat_id=update.message.chat_id,
                message_id=active_processes[process_id]["status_message"].message_id
            )
            # Remove the process from active_processes
            del active_processes[process_id]
    except Exception as e:
        logger.error(f"Error deleting status message: {str(e)}")

async def handle_resites_command(update: Update, context: CallbackContext):
    """
    Handle the /resites command for rechecking all user sites.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    logger.info(f"Resites command received from user {user_id} ({first_name})")
    
    # Check if user has an active plan (not Trial)
    from plans import get_user_current_tier
    user_tier = get_user_current_tier(user_id)
    
    if user_tier == "Trial":
        await update.message.reply_text(
            """<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝘼𝙘𝙘𝙚𝙨𝙨 𝘿𝙚𝙣𝙞𝙙 ⛔</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>This command is only available for users with an active plan.</i>

<i>Upgrade your plan to use site management features.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        logger.info(f"Resites command denied for trial user {user_id}")
        return
    
    # Get user's current sites
    user_sites = get_user_sites(user_id)
    
    if not user_sites:
        await update.message.reply_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙉𝙤 𝙎𝙞𝙩𝙚𝙨 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>You don't have any sites configured.</i>

<i>Please add at least one site using the /seturl command.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        return
    
    # Generate a unique process ID for this command
    import time
    process_id = f"{user_id}_{int(time.time())}"
    
    # Send initial progress message
    progress_msg = f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 📊</pre>
<a href='https://t.me/failfr'>⊀</a> 𝐆𝚊𝐭𝐞𝐰𝚊𝐲 ↬ Site Revalidation
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐨𝐭𝚊𝐥 𝐒𝐢𝐭𝐞𝐬 ↬ <code>{len(user_sites)}</code>
<a href='https://t.me/failfr'>⊀</a> 𝐓𝐞𝐬𝐭𝐞𝐝 ↬ <code>0/{len(user_sites)} (0%)</code>
<a href='https://t.me/failfr'>⊀</a> ✅ 𝐖𝐨𝐫𝐤𝐢𝐧𝐠 ↬ <code>0</code>
<a href='https://t.me/failfr'>⊀</a> ❌ 𝐃𝐞𝐚𝐝 ↬ <code>0</code>
<a href='https://t.me/failfr'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    status_message = await update.message.reply_text(
        progress_msg,
        parse_mode="HTML"
    )
    
    # Store the process information in the active_processes dictionary
    active_processes[process_id] = {
        "status_message": status_message,
        "user_id": user_id
    }
    
    # Process sites in background
    asyncio.create_task(_process_resites_sites(update, context, process_id))

async def handle_delall_callback(update: Update, context: CallbackContext):
    """
    Handle the callback from the delall confirmation button.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    callback_data = query.data
    
    if callback_data == "delall_cancel":
        await query.edit_message_text(
            f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙊𝙥𝙚𝙧𝙖𝙩𝙞𝙤𝙣 𝘾𝙖𝙣𝙘𝙚𝙡𝙚𝙙 ❌</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Your sites have not been deleted.</i>

<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failedfr'>kคli liຖนxx</a>""",
            parse_mode="HTML"
        )
        return
    
    if callback_data.startswith("delall_confirm_"):
        try:
            callback_user_id = int(callback_data.split("_")[2])
            
            # Check if the user who clicked is the same as the one who initiated the command
            if callback_user_id != user_id:
                await query.answer(
                    text="⛔ Not your business!",
                    show_alert=True
                )
                return
            
            # Remove all sites for the user
            if remove_all_user_sites(user_id):
                await query.edit_message_text(
                    f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙎𝙪𝘾𝙘𝙚𝙨𝙨 ✅</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>All sites deleted successfully!</i>

<i>You can add new sites using the /seturl command.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                    parse_mode="HTML"
                )
                logger.info(f"User {user_id} deleted all sites")
            else:
                await query.edit_message_text(
                    f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Failed to delete sites!</i>

<i>Please try again later.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                    parse_mode="HTML"
                )
                logger.error(f"Failed to delete all sites for user {user_id}")
        except (ValueError, IndexError) as e:
            logger.error(f"Error processing delall callback: {str(e)}")
            await query.edit_message_text(
                f"""<pre>⩙ 𝑺𝒕𝒂𝒕𝒖𝒔 ↬ 𝙀𝙧𝙧𝙤𝙧 ⚠️</pre>
<a href='https://t.me/abtlnx'>⊀</a> 𝐌𝐞𝐬𝐬𝐚𝐠𝐞 ↬ <i>Error processing request!</i>

<i>Please try again.</i>
<a href='https://t.me/abtlnx'>⌬</a> 𝐃𝐞𝐯 ↬ <a href='https://t.me/abtlnx'>kคli liຖนxx</a>""",
                parse_mode="HTML"
            )
