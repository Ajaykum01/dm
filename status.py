import os
import sys
import time
import socket
import platform
import psutil
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

# Import database functions
from database import get_or_create_user, connection_pool, get_total_users

# Import logger
import logging

# Configure logger for this module
logger = logging.getLogger(__name__)

# UI Elements
BULLET_LINK = "⌬"
BULLET_POINT = "⊀"
ARROW_RIGHT = "↬"
SECTION_DIVIDER = "――――――――――――――"

# Store bot start time for uptime calculation
BOT_START_TIME = time.time()

def get_uptime() -> str:
    """Get system uptime in days, hours, minutes, and seconds."""
    boot_time = psutil.boot_time()
    uptime_seconds = int(time.time() - boot_time)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

def get_bot_uptime() -> str:
    """Get bot uptime in days, hours, minutes, and seconds."""
    uptime_seconds = int(time.time() - BOT_START_TIME)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours:02}:{minutes:02}:{seconds:02}"

def create_progress_bar(percentage: float, length: int = 10) -> str:
    """Create a visual progress bar for resource usage."""
    filled_length = int(length * percentage / 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"{bar} {percentage:.1f}%"

def get_system_info() -> dict:
    """Gather system information with error handling."""
    try:
        # CPU info
        cpu_usage = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_model = platform.processor() or "N/A"

        # RAM info
        memory = psutil.virtual_memory()
        total_memory = memory.total / (1024 ** 3)  # GB
        used_memory = memory.used / (1024 ** 3)
        available_memory = memory.available / (1024 ** 3)
        memory_percent = memory.percent

        # Swap info
        swap = psutil.swap_memory()
        total_swap = swap.total / (1024 ** 3)
        used_swap = swap.used / (1024 ** 3)
        swap_percent = swap.percent

        # Disk info
        disk = psutil.disk_usage("/")
        total_disk = disk.total / (1024 ** 3)  # GB
        used_disk = disk.used / (1024 ** 3)
        free_disk = disk.free / (1024 ** 3)
        disk_percent = disk.percent

        # Host/VPS info
        hostname = socket.gethostname()
        os_name = platform.system()
        os_version = platform.version()
        architecture = platform.machine()

        # Network info
        network = psutil.net_io_counters()
        bytes_sent = network.bytes_sent / (1024 ** 2)  # MB
        bytes_recv = network.bytes_recv / (1024 ** 2)  # MB
        network_interfaces = psutil.net_if_addrs()
        active_interfaces = [iface for iface in network_interfaces.keys() if not iface.startswith(('lo', 'docker', 'br-'))]

        # Uptime
        uptime_str = get_uptime()
        bot_uptime_str = get_bot_uptime()

        # Current time
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Bot restart time
        bot_restart_time = datetime.fromtimestamp(BOT_START_TIME).strftime("%Y-%m-%d %H:%M:%S")

        # Check if resources are critically low
        cpu_critical = cpu_usage > 90
        memory_critical = memory_percent > 90
        disk_critical = disk_percent > 90

        return {
            "cpu_usage": cpu_usage,
            "cpu_count": cpu_count,
            "cpu_freq": cpu_freq.current if cpu_freq else 0,
            "cpu_model": cpu_model,
            "total_memory": total_memory,
            "used_memory": used_memory,
            "available_memory": available_memory,
            "memory_percent": memory_percent,
            "total_swap": total_swap,
            "used_swap": used_swap,
            "swap_percent": swap_percent,
            "total_disk": total_disk,
            "used_disk": used_disk,
            "free_disk": free_disk,
            "disk_percent": disk_percent,
            "hostname": hostname,
            "os_name": os_name,
            "os_version": os_version,
            "architecture": architecture,
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
            "active_interfaces": active_interfaces,
            "uptime_str": uptime_str,
            "bot_uptime_str": bot_uptime_str,
            "current_time": current_time,
            "bot_restart_time": bot_restart_time,
            "cpu_critical": cpu_critical,
            "memory_critical": memory_critical,
            "disk_critical": disk_critical,
            "error": None
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {
            "error": str(e),
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /status command to show bot and VPS status."""
    try:
        # Get system information
        sys_info = get_system_info()
        
        # Check for errors
        if sys_info.get("error"):
            error_message = (
                f"{BULLET_LINK} 𝐄𝐫𝐫𝐨𝐫 {ARROW_RIGHT} <code>❌ {sys_info['error']}</code>\n"
                f"{SECTION_DIVIDER}\n"
                f"{BULLET_LINK} 𝐓𝐢𝐦𝐞 {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
                f"{BULLET_LINK} 𝐁𝐨𝐭 𝐁𝐲 {ARROW_RIGHT} <a href='tg://resolve?domain=Kalinuxxx'>kคli liຖนxx</a>\n"
            )
            await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)
            return
        
        # Get total users from database using the function from database.py
        total_users = get_total_users()
        
        # Check database connection
        db_status = "✅ Active"
        try:
            with connection_pool.getconn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            db_status = "❌ Error"
        
        # Format OS version to show only relevant part
        os_version_short = sys_info["os_version"].split("-")[0] if "-" in sys_info["os_version"] else sys_info["os_version"]
        
        # Create progress bars for visual representation
        cpu_bar = create_progress_bar(sys_info["cpu_usage"])
        memory_bar = create_progress_bar(sys_info["memory_percent"])
        disk_bar = create_progress_bar(sys_info["disk_percent"])
        
        # Create the status message with improved formatting
        status_message = (
            f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬</b> {ARROW_RIGHT} <code>✅ Active</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['bot_uptime_str']}</code>\n"
            f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['uptime_str']}</code>\n"
            f"{BULLET_LINK} <b>𝐋𝐚𝐬𝐭 𝐑𝐞𝐬𝐭𝐚𝐫𝐭</b> {ARROW_RIGHT} <code>{sys_info['bot_restart_time']}</code>\n"
            f"{BULLET_LINK} <b>𝐂𝐮𝐫𝐫𝐞𝐧𝐭 𝐓𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦</b> {ARROW_RIGHT} <code>{sys_info['os_name']} {os_version_short}</code>\n"
            f"{BULLET_LINK} <b>𝐀𝐫𝐜𝐡𝐢𝐭𝐞𝐜𝐭𝐮𝐫𝐞</b> {ARROW_RIGHT} <code>{sys_info['architecture']}</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐂𝐏𝐔</b> {ARROW_RIGHT} <code>{sys_info['cpu_usage']:.1f}% ({sys_info['cpu_count']} cores @ {sys_info['cpu_freq']:.0f}MHz)</code>\n"
            f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{cpu_bar}</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐑𝐀𝐌</b> {ARROW_RIGHT} <code>{sys_info['used_memory']:.2f}GB / {sys_info['total_memory']:.2f}GB</code>\n"
            f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{memory_bar}</code>\n"
            f"{BULLET_POINT} <b>Available</b> {ARROW_RIGHT} <code>{sys_info['available_memory']:.2f}GB</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐃𝐢𝐬𝐤</b> {ARROW_RIGHT} <code>{sys_info['used_disk']:.2f}GB / {sys_info['total_disk']:.2f}GB</code>\n"
            f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{disk_bar}</code>\n"
            f"{BULLET_POINT} <b>Free</b> {ARROW_RIGHT} <code>{sys_info['free_disk']:.2f}GB</code>\n"
            f"{SECTION_DIVIDER}\n"
            
            f"{BULLET_LINK} <b>𝐍𝐞𝐭𝐰𝐨𝐫𝐤</b> {ARROW_RIGHT} <code>↑ {sys_info['bytes_sent']:.1f}MB ↓ {sys_info['bytes_recv']:.1f}MB</code>\n"
            f"{BULLET_POINT} <b>Active Interfaces</b> {ARROW_RIGHT} <code>{', '.join(sys_info['active_interfaces'][:3])}</code>\n"
        )
        
        # Add warning if resources are critically low
        if sys_info["cpu_critical"] or sys_info["memory_critical"] or sys_info["disk_critical"]:
            warning_message = "\n⚠️ <b>Warning:</b> System resources are critically low!"
            status_message += warning_message
        
        # Add bot info at the end
        status_message += f"\n{SECTION_DIVIDER}\n{BULLET_LINK} <b>𝐁𝐨𝐭 𝐁𝐲</b> {ARROW_RIGHT} <a href='tg://resolve?domain=Kalinuxxx'>kคli liຖนxx</a>"
        
        # Create refresh button
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send the status message with refresh button
        await update.message.reply_text(
            status_message, 
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await update.message.reply_text(
            f"⚠️ <b>Error:</b> <code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )

async def refresh_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the refresh button callback."""
    query = update.callback_query
    await query.answer("Refreshing status...")
    
    # Get system information
    sys_info = get_system_info()
    
    # Check for errors
    if sys_info.get("error"):
        error_message = (
            f"{BULLET_LINK} 𝐄𝐫𝐫𝐨𝐫 {ARROW_RIGHT} <code>❌ {sys_info['error']}</code>\n"
            f"{SECTION_DIVIDER}\n"
            f"{BULLET_LINK} 𝐓𝐢𝐦𝐞 {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
            f"{BULLET_LINK} 𝐁𝐨𝐭 𝐁𝐲 {ARROW_RIGHT} <a href='tg://resolve?domain=Kalinuxxx'>kคli liຖนxx</a>\n"
        )
        await query.edit_message_text(error_message, parse_mode=ParseMode.HTML)
        return
    
    # Get total users from database using the function from database.py
    total_users = get_total_users()
    
    # Check database connection
    db_status = "✅ Active"
    try:
        with connection_pool.getconn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        db_status = "❌ Error"
    
    # Format OS version to show only relevant part
    os_version_short = sys_info["os_version"].split("-")[0] if "-" in sys_info["os_version"] else sys_info["os_version"]
    
    # Create progress bars for visual representation
    cpu_bar = create_progress_bar(sys_info["cpu_usage"])
    memory_bar = create_progress_bar(sys_info["memory_percent"])
    disk_bar = create_progress_bar(sys_info["disk_percent"])
    
    # Create the status message with improved formatting
    status_message = (
        f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐒𝐭𝐚𝐭𝐮𝐬</b> {ARROW_RIGHT} <code>✅ Active</code>\n"
        f"{BULLET_LINK} <b>𝐃𝐚𝐭𝐚𝐛𝐚𝐬𝐞</b> {ARROW_RIGHT} <code>{db_status}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐓𝐨𝐭𝐚𝐥 𝐔𝐬𝐞𝐫𝐬</b> {ARROW_RIGHT} <code>{total_users}</code>\n"
        f"{BULLET_LINK} <b>𝐁𝐨𝐭 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['bot_uptime_str']}</code>\n"
        f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦 𝐔𝐩𝐭𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['uptime_str']}</code>\n"
        f"{BULLET_LINK} <b>𝐋𝐚𝐬𝐭 𝐑𝐞𝐬𝐭𝐚𝐫𝐭</b> {ARROW_RIGHT} <code>{sys_info['bot_restart_time']}</code>\n"
        f"{BULLET_LINK} <b>𝐂𝐮𝐫𝐫𝐞𝐧𝐭 𝐓𝐢𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['current_time']}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐒𝐲𝐬𝐭𝐞𝐦</b> {ARROW_RIGHT} <code>{sys_info['os_name']} {os_version_short}</code>\n"
        f"{BULLET_LINK} <b>𝐀𝐫𝐜𝐡𝐢𝐭𝐞𝐜𝐭𝐮𝐫𝐞</b> {ARROW_RIGHT} <code>{sys_info['architecture']}</code>\n"
        f"{BULLET_LINK} <b>𝐇𝐨𝐬𝐭𝐧𝐚𝐦𝐞</b> {ARROW_RIGHT} <code>{sys_info['hostname']}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐂𝐏𝐔</b> {ARROW_RIGHT} <code>{sys_info['cpu_usage']:.1f}% ({sys_info['cpu_count']} cores @ {sys_info['cpu_freq']:.0f}MHz)</code>\n"
        f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{cpu_bar}</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐑𝐀𝐌</b> {ARROW_RIGHT} <code>{sys_info['used_memory']:.2f}GB / {sys_info['total_memory']:.2f}GB</code>\n"
        f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{memory_bar}</code>\n"
        f"{BULLET_POINT} <b>Available</b> {ARROW_RIGHT} <code>{sys_info['available_memory']:.2f}GB</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐃𝐢𝐬𝐤</b> {ARROW_RIGHT} <code>{sys_info['used_disk']:.2f}GB / {sys_info['total_disk']:.2f}GB</code>\n"
        f"{BULLET_POINT} <b>Usage</b> {ARROW_RIGHT} <code>{disk_bar}</code>\n"
        f"{BULLET_POINT} <b>Free</b> {ARROW_RIGHT} <code>{sys_info['free_disk']:.2f}GB</code>\n"
        f"{SECTION_DIVIDER}\n"
        
        f"{BULLET_LINK} <b>𝐍𝐞𝐭𝐰𝐨𝐫𝐤</b> {ARROW_RIGHT} <code>↑ {sys_info['bytes_sent']:.1f}MB ↓ {sys_info['bytes_recv']:.1f}MB</code>\n"
        f"{BULLET_POINT} <b>Active Interfaces</b> {ARROW_RIGHT} <code>{', '.join(sys_info['active_interfaces'][:3])}</code>\n"
    )
    
    # Add warning if resources are critically low
    if sys_info["cpu_critical"] or sys_info["memory_critical"] or sys_info["disk_critical"]:
        warning_message = "\n⚠️ <b>Warning:</b> System resources are critically low!"
        status_message += warning_message
    
    # Add bot info at the end
    status_message += f"\n{SECTION_DIVIDER}\n{BULLET_LINK} <b>𝐁𝐨𝐭 𝐁𝐲</b> {ARROW_RIGHT} <a href='tg://resolve?domain=Kalinuxxx'>kคli liຖนxx</a>"
    
    # Create refresh button
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Edit the message with updated status
    await query.edit_message_text(
        status_message, 
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

# Register the callback handler for the refresh button
def register_status_handlers(application):
    """Register status command handlers with the application."""
    application.add_handler(CallbackQueryHandler(refresh_status_callback, pattern="refresh_status"))
