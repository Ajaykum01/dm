import logging
from typing import Dict, Optional
from datetime import datetime
import pytz  # Added for timezone handling
from database import get_or_create_user, get_user_credits  # Import database functions
from plans import get_user_current_tier  # Import tier checking function

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("credits_command.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Define Indian timezone
IST = pytz.timezone('Asia/Kolkata')

# Function to convert datetime to Indian format
def format_indian_datetime(dt: datetime) -> str:
    """
    Convert datetime to Indian format (DD/MM/YY HH:MM:SS).
    
    Args:
        dt: Datetime object
        
    Returns:
        Formatted string in Indian format
    """
    # Ensure dt is timezone-aware, assume UTC if not
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    # Convert to IST
    ist_dt = dt.astimezone(IST)
    
    # Format as DD/MM/YY HH:MM:SS
    return ist_dt.strftime('%d/%m/%y %H:%M:%S')

def format_credits_response(user_info: Dict) -> str:
    """
    Format credits information into a beautiful message with emojis.
    
    Args:
        user_info: Dictionary containing user information
        
    Returns:
        Formatted string with emojis
    """
    # Get user info
    user_id = user_info.get("id", "Unknown")
    username = user_info.get("username", "")
    first_name = user_info.get("first_name", "User")
    
    # Get user data from database
    try:
        user_data = get_or_create_user(user_id, username)
        if not user_data:
            # Fallback if database fails
            tier = "Unknown"
            credits = 0
            joined_date = datetime.now()  # Use current time as fallback
            logger.error(f"Failed to get user data for user {user_id}")
        else:
            # Unpack all values including join date
            _, joined_date, tier, _ = user_data
    except Exception as e:
        logger.error(f"Error getting user data for {user_id}: {str(e)}")
        tier = "Unknown"
        credits = 0
        joined_date = datetime.now()  # Use current time as fallback
    
    # Get user credits from database
    try:
        user_credits = get_user_credits(user_id)
        if user_credits is None:
            credits_display = "Error"
            logger.error(f"Failed to get credits for user {user_id}")
        elif user_credits == float('inf'):
            credits_display = "Infinite😎"  # Display for unlimited credits
        else:
            credits_display = str(user_credits)
    except Exception as e:
        logger.error(f"Error getting credits for {user_id}: {str(e)}")
        credits_display = "Error"
    
    # Get user tier from plans module
    try:
        user_tier = get_user_current_tier(user_id)
        if user_tier:
            tier = user_tier
    except Exception as e:
        logger.error(f"Error getting user tier for {user_id}: {str(e)}")
        # Keep tier from user_data as fallback
    
    # Format join date in Indian time format
    formatted_joined_date = format_indian_datetime(joined_date)
    
    # Create user link with profile name hyperlinked
    if username:
        user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{tier}]</code>"
    else:
        user_link = f"<a href='tg://user?id={user_id}'>{first_name}</a> <code>[{tier}]</code>"
    
    # Determine credit status with appropriate emoji
    if credits_display == "Infinite😎":
        credit_status = "🔥"
    elif credits_display == "Error":
        credit_status = "❌"
    elif isinstance(credits_display, str) and credits_display.isdigit():
        credits_num = int(credits_display)
        if credits_num > 50:
            credit_status = "✅"
        elif credits_num > 10:
            credit_status = "⚠️"
        else:
            credit_status = "🔴"
    else:
        credit_status = "❌"
    
    # Format response with exact structure as /rz command
    formatted_response = f"""<pre><a href='https://t.me/abtlnx'>⩙</a> <b>𝑼𝒔𝒆𝒓 𝑰𝒏𝒇𝒐</b></pre>
<a href='https://t.me/failurefr_07'>⊀</a> <b>𝐈𝐃</b> ↬ <code>{user_id}</code>
<a href='https://t.me/failurefr_07'>⊀</a> <b>𝐔𝐬𝐞𝐫</b> ↬ @{username if username else "None"}
<a href='https://t.me/failurefr_07'>⊀</a> <b>𝐍𝐚𝐦𝐞</b> ↬ {user_link}
<a href='https://t.me/failurefr_07'>⊀</a> <b>𝐂𝐫𝐞𝐝𝐢𝐭𝐬</b> ↬ <code>{credits_display}</code> {credit_status}
<a href='https://t.me/failurefr_07'>⊀</a> <b>𝐉𝐨𝐢𝐧𝐞𝐝</b> ↬ <code>{formatted_joined_date}</code>
<a href='https://t.me/failurefr_07'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""
    
    return formatted_response

# This function will be called from main.py
async def handle_credits_command(update, context):
    """
    Handle the /credits command.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
    # Prepare user info
    user_info = {
        "id": user_id,
        "username": username,
        "first_name": first_name
    }
    
    # Format the response
    result = format_credits_response(user_info)
    
    # Send credits information
    await update.message.reply_text(result, parse_mode="HTML")

if __name__ == "__main__":
    # For testing purposes
    test_user = {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test"
    }
    print(format_credits_response(test_user))
