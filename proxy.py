import re
import logging
import aiohttp
import asyncio
import random
from typing import Dict, List, Optional, Tuple
from database import get_or_create_user, add_user_proxy, remove_user_proxies, get_user_proxies, get_random_user_proxy
from plans import get_user_current_tier
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test site for proxy testing - changed to ipify
TEST_SITE = "https://api.ipify.org?format=json"  # Using ipify to check if proxy is working

# Dictionary to store last command time for each user (for cooldown)
last_command_time = {}

def auto_fix_proxy_format(raw_proxy: str) -> Optional[str]:
    """
    Auto-detects and corrects various proxy formats to 'http://user:pass@host:port'.
    Handles:
    - IP:Port:User:Pass
    - Domain:Port:User:Pass (Fixed to support this)
    - User:Pass@IP:Port
    - http://IP:Port (Transparent)
    - IP:Port (Transparent)
    - Protocols (http/https) and typos (hytp)
    - Colons in passwords
    
    Args:
        raw_proxy: Raw proxy string
        
    Returns:
        Normalized proxy string (http://user:pass@host:port) or None if invalid
    """
    if not raw_proxy:
        return None

    # 1. Clean the string
    p = raw_proxy.strip()
    
    # 2. Handle protocol typo
    if p.startswith('hytp://'):
        p = 'http://' + p[7:]
    
    # 3. Extract protocol if present
    protocol = "http"
    if p.startswith(('http://', 'https://')):
        parts = p.split('://', 1)
        protocol = parts[0] 
        core = parts[1]
    else:
        core = p

    # 4. Analyze the core structure (without protocol)
    
    # Case A: Contains '@' (Standard format)
    if '@' in core:
        # Split by last '@' to handle passwords that might contain '@'
        auth_part, host_port_part = core.rsplit('@', 1)
        
        # Validate host:port part
        if ':' in host_port_part:
            # It looks like user:pass@host:port
            return f"{protocol}://{auth_part}@{host_port_part}"
        else:
            # Invalid structure after @
            return None

    # Case B: No '@' (Could be Host:Port:User:Pass or Host:Port)
    parts = core.split(':')
    
    # Check if it looks like Host:Port:User:Pass
    # We check if there are at least 4 parts and the second part (port) is numeric
    if len(parts) >= 4 and parts[1].isdigit():
        # parts[0] = Host (IP or Domain), parts[1] = Port, parts[2] = User, parts[3:] = Pass
        host = parts[0]
        port = parts[1]
        user = parts[2]
        # Password might contain colons, so join the rest
        password = ':'.join(parts[3:])
        return f"{protocol}://{user}:{password}@{host}:{port}"
        
    # Check if it looks like Transparent Proxy (Host:Port)
    # We check if there are exactly 2 parts and the second part is numeric
    if len(parts) == 2 and parts[1].isdigit():
         return f"{protocol}://{parts[0]}:{parts[1]}"

    # If nothing matches
    return None

def normalize_proxy_format(proxy: str) -> str:
    """
    Wrapper for auto_fix_proxy_format to maintain compatibility with existing code.
    """
    # Attempt to fix the format
    fixed = auto_fix_proxy_format(proxy)
    if fixed:
        return fixed
    
    # Fallback to basic cleanup if auto-fix failed but we want to try anyway
    proxy = proxy.strip()
    if proxy.startswith('hytp://'):
        proxy = 'http://' + proxy[7:]
    if not proxy.startswith(('http://', 'https://')):
        return f"http://{proxy}"
    return proxy

async def test_proxy(proxy: str) -> Tuple[bool, str]:
    """
    Test if a proxy works by making a request to a test site.
    
    Args:
        proxy: Proxy string to test
        
    Returns:
        Tuple of (success, message)
    """
    # Normalize proxy format
    normalized_proxy = normalize_proxy_format(proxy)
    
    try:
        # Create an aiohttp session for async HTTP requests with proper timeout
        timeout = aiohttp.ClientTimeout(total=15)  # 15 seconds timeout
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Make a request through the proxy to the test site
            async with session.get(TEST_SITE, proxy=normalized_proxy) as response:
                response.raise_for_status()
                # Parse the JSON response to verify it's a valid IP
                data = await response.json()
                if 'ip' in data and data['ip']:
                    # If we get a valid IP in the response, the proxy is working
                    return True, f"Proxy working successfully (IP: {data['ip']})"
                else:
                    return False, "Invalid response from ipify API"
    
    except Exception as e:
        logger.error(f"Error testing proxy: {e}")
        return False, f"Proxy is dead: {str(e)}"

async def handle_proxy_command(update, context):
    """
    Handle the /proxy command to add proxies.
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
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
    
    # Check if user provided proxies
    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ <b>Missing proxy!</b>\n\n"
            "<i>Usage: /proxy username:password@host:port</i>\n\n"
            "<i>Or reply to a message containing proxies with /proxy</i>",
            parse_mode="HTML"
        )
        return
    
    # Get proxies from command or replied message
    proxy_text = ""
    
    if context.args:
        proxy_text = " ".join(context.args)
    elif update.message.reply_to_message:
        replied_message = update.message.reply_to_message
        if replied_message.text:
            proxy_text = replied_message.text
        elif replied_message.document and replied_message.document.mime_type == "text/plain":
            file = await context.bot.get_file(replied_message.document.file_id)
            file_content = await file.download_as_bytearray()
            proxy_text = file_content.decode('utf-8')
    
    # Split text into individual lines
    proxy_lines = proxy_text.split('\n')
    
    # Parse and auto-fix proxies
    candidates = []
    for line in proxy_lines:
        if not line.strip():
            continue
        # If line contains spaces, split it
        parts = line.split()
        candidates.extend(parts)
    
    proxies = []
    for raw in candidates:
        raw = raw.strip()
        if not raw: continue
        
        # Use the auto-fix function to handle any format
        normalized = auto_fix_proxy_format(raw)
        
        if normalized:
            proxies.append(normalized)
    
    # Check if any valid proxies were found
    if not proxies:
        await update.message.reply_text(
            "⚠️ <b>No valid proxies found!</b>\n\n"
            "<i>Couldn't recognize the proxy format. Please check your input.</i>",
            parse_mode="HTML"
        )
        return
    
    # Check if user has reached the proxy limit
    current_proxies = get_user_proxies(user_id)
    if len(current_proxies) >= 10:
        await update.message.reply_text(
            "⚠️ <b>Proxy limit reached!</b>\n\n"
            "<i>You can only have up to 10 proxies. Use /rproxy to remove some proxies first.</i>",
            parse_mode="HTML"
        )
        return
    
    # Limit the number of proxies to add
    max_add = 10 - len(current_proxies)
    if len(proxies) > max_add:
        proxies = proxies[:max_add]
        await update.message.reply_text(
            f"⚠️ <b>Too many proxies!</b>\n\n"
            f"<i>You can only add {max_add} more proxies. Only the first {max_add} will be processed.</i>",
            parse_mode="HTML"
        )
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Send a processing message with the same style as chk.py
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>𝗣𝗿𝗼𝗰𝗲𝘀𝗶𝗻𝗴 𝗥𝗲𝗾𝘂𝗲𝘀𝘁...</b></pre>
<pre>{len(proxies)} proxies</pre>
𝐆𝐚𝐭𝐞𝐰𝐚𝐲 ↬ <i>𝙋𝙧𝙤𝙭𝙮 𝙏𝙚𝙨𝙩</i>""",
        parse_mode="HTML"
    )
    
    # Create a background task to process proxy testing
    asyncio.create_task(process_proxy_test(proxies, user_id, first_name, processing_message, context))

async def process_proxy_test(proxies: List[str], user_id: int, first_name: str, processing_message, context):
    """
    Process proxy testing in the background.
    """
    try:
        # Test all proxies in parallel with a semaphore to limit concurrent connections
        semaphore = asyncio.Semaphore(20)  # Limit to 20 concurrent requests
        tasks = [test_proxy_with_semaphore(semaphore, proxy) for proxy in proxies]
        results = await asyncio.gather(*tasks)
        
        # Process the results
        successful_proxies = []
        failed_proxies = []
        
        for proxy, (is_working, message) in zip(proxies, results):
            if is_working:
                success, db_message = add_user_proxy(user_id, proxy)
                if success:
                    successful_proxies.append((proxy, message))
                else:
                    failed_proxies.append((proxy, db_message))
            else:
                failed_proxies.append((proxy, message))
        
        # Format the successful proxies list
        successful_list = ""
        for i, (proxy, message) in enumerate(successful_proxies):
            parts = proxy.split("://")
            if len(parts) == 2:
                auth_host = parts[1]
                auth_parts = auth_host.split("@")
                if len(auth_parts) == 2:
                    auth = auth_parts[0]
                    host_port = auth_parts[1]
                    username = auth.split(":")[0]
                    masked_auth = f"{username}:******"
                    successful_list += f"{i+1}. http://{masked_auth}@{host_port} - {message}\n"
        
        # Format the failed proxies list
        failed_list = ""
        for i, (proxy, message) in enumerate(failed_proxies):
            parts = proxy.split("://")
            if len(parts) == 2:
                auth_host = parts[1]
                auth_parts = auth_host.split("@")
                if len(auth_parts) == 2:
                    auth = auth_parts[0]
                    host_port = auth_parts[1]
                    username = auth.split(":")[0]
                    masked_auth = f"{username}:******"
                    failed_list += f"{i+1}. http://{masked_auth}@{host_port} - {message}\n"
            else:
                auth_parts = proxy.split("@")
                if len(auth_parts) == 2:
                    auth = auth_parts[0]
                    host_port = auth_parts[1]
                    username = auth.split(":")[0]
                    masked_auth = f"{username}:******"
                    failed_list += f"{i+1}. {masked_auth}@{host_port} - {message}\n"
        
        # Create a properly formatted message to avoid HTML parsing errors
        message_text = (
            f"<pre><a href='https://t.me/abtlnx'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙍𝙚𝙨𝙪𝙡𝙩𝙨</b> &#x1f4ca;</pre>\n"
            f"<a href='https://t.me/abtlnx'>&#x2140;</a> <b>𝐒𝐮𝐜𝐜𝐞𝐬𝐬𝐟𝐮𝐥</b> ↬ <code>{len(successful_proxies)} proxies</code>\n"
        )
        
        if successful_list:
            message_text += f"<pre>{successful_list}</pre>\n"
        
        message_text += (
            f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐅𝐚𝐢𝐥𝐞𝐝</b> ↬ <code>{len(failed_proxies)} proxies</code>\n"
        )
        
        if failed_list:
            message_text += f"<pre>{failed_list}</pre>\n"
        
        message_text += (
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
        )
        
        # Update the processing message with the result
        await processing_message.edit_text(
            message_text,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in process_proxy_test: {str(e)}")
        # Create a properly formatted error message
        error_message = (
            f"<pre><a href='https://t.me/failfr'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙀𝙧𝙧𝙤𝙧</b> &#x274c;</pre>\n"
            f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>An error occurred while testing proxies: {str(e)}</code>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
        )
        
        # Update the processing message with the error
        await processing_message.edit_text(
            error_message,
            parse_mode="HTML"
        )

async def test_proxy_with_semaphore(semaphore, proxy: str) -> Tuple[bool, str]:
    """
    Test a proxy with a semaphore to limit concurrent connections.
    """
    async with semaphore:
        return await test_proxy(proxy)

async def handle_rproxy_command(update, context):
    """
    Handle the /rproxy command to remove proxies.
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
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
    
    # Check if user provided a count
    if not context.args:
        # If no count provided, remove all proxies
        count = -1
    else:
        # Get count from command
        try:
            count = int(context.args[0])
        except ValueError:
            await update.message.reply_text(
                "⚠️ <b>Invalid count!</b>\n\n"
                "<i>Usage: /rproxy 5 (to remove 5 proxies)</i>\n"
                "<i>Usage: /rproxy (to remove all proxies)</i>",
                parse_mode="HTML"
            )
            return
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Remove proxies from the database
    success, message = remove_user_proxies(user_id, count)
    
    # Create a properly formatted message
    if success:
        if count == -1:
            message_text = (
                f"<pre><a href='https://t.me/failfr'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙎𝙪𝙘𝙘𝙚𝙨𝙨</b> &#x2705;</pre>\n"
                f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐦𝐨𝐯𝐞𝐝</b> ↬ <code>All proxies</code>\n"
                f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>\n"
                f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
                f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
            )
        else:
            message_text = (
                f"<pre><a href='https://t.me/failfr'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙎𝙪𝙘𝙘𝙚𝙨𝙨</b> &#x2705;</pre>\n"
                f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐦𝐨𝐯𝐞𝐝</b> ↬ <code>{count} proxies</code>\n"
                f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>\n"
                f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
                f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
            )
    else:
        message_text = (
            f"<pre><a href='https://t.me/failfr'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙀𝙧𝙧𝙤𝙧</b> &#x274c;</pre>\n"
            f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐦𝐨𝐯𝐞𝐝</b> ↬ <code>{count if count != -1 else 'All'} proxies</code>\n"
            f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>{message}</code>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
        )
    
    # Send the result with the same style as chk.py
    await update.message.reply_text(
        message_text,
        parse_mode="HTML"
    )

async def handle_myproxy_command(update, context):
    """
    Handle the /myproxy command to list user's proxies.
    """
    # Get user info
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users (user-specific)
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
    
    # Update the last command time for Free/Trial users immediately
    if user_tier in ["Trial", "Free"]:
        last_command_time[user_id] = current_time
    
    # Get user proxies
    proxies = get_user_proxies(user_id)
    
    # Check if user has any proxies
    if not proxies:
        message_text = (
            f"<pre><a href='https://t.me/failfr'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙄𝙣𝙛𝙤</b> &#x2139;&#xfe0f;</pre>\n"
            f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐏𝐫𝐨𝐱𝐢𝐞𝐬</b> ↬ <code>0/10</code>\n"
            f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <code>You don't have any proxies. Use /proxy username:password@host:port to add a proxy.</code>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
        )
        
        await update.message.reply_text(
            message_text,
            parse_mode="HTML"
        )
        return
    
    # Format the proxy list (masking passwords for security)
    proxy_list = ""
    for i, proxy in enumerate(proxies):
        # Extract username, password, host, and port
        parts = proxy.split("://")
        if len(parts) == 2:
            protocol = parts[0]
            auth_host = parts[1]
            auth_parts = auth_host.split("@")
            if len(auth_parts) == 2:
                auth = auth_parts[0]
                host_port = auth_parts[1]
                username = auth.split(":")[0]
                # Mask the password
                masked_auth = f"{username}:******"
                proxy_list += f"{i+1}. {protocol}://{masked_auth}@{host_port}\n"
    
    # Create a properly formatted message
    message_text = (
        f"<pre><a href='https://t.me/failfr'>&#x2a9d;</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝙇𝙞𝙨𝙩</b> &#x1f4cb;</pre>\n"
        f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐏𝐫𝐨𝐱𝐢𝐞𝐬</b> ↬ <code>{len(proxies)}/10</code>\n"
        f"<a href='https://t.me/failfr'>&#x2140;</a> <b>𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞</b> ↬ <pre>{proxy_list}</pre>\n"
        f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐔𝐬𝐞𝐫</b> ↬ <a href='tg://user?id={user_id}'>{first_name}</a>\n"
        f"<a href='https://t.me/failfr'>&#x232c;</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"
    )
    
    # Send the result with the same style as chk.py
    await update.message.reply_text(
        message_text,
        parse_mode="HTML"
    )
