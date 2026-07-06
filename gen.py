import re
import random
import time
import io
import asyncio
from typing import List, Dict, Tuple, Optional
from bin import get_bin_info
from telegram import Update, InputFile
from telegram.ext import CallbackContext
import logging
from datetime import datetime, timedelta
from plans import get_user_current_tier
from database import get_user_credits, update_user_credits

# Configure logging
logger = logging.getLogger(__name__)

# Dictionary to track last command time for each user (for cooldown)
last_command_time = {}

def luhn_check(card_number: str) -> bool:
    """
    Validate a card number using the Luhn algorithm.
    
    Args:
        card_number: Card number as string
        
    Returns:
        True if valid, False otherwise
    """
    # Convert to list of integers
    digits = [int(d) for d in card_number]
    
    # Double every second digit from the right
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] = (digits[i] // 10) + (digits[i] % 10)
    
    # Sum all digits
    total = sum(digits)
    
    # Check if divisible by 10
    return total % 10 == 0

def generate_luhn_card(prefix: str, length: int = 16) -> str:
    """
    Generate a valid credit card number using the Luhn algorithm.
    
    Args:
        prefix: The BIN or prefix to start the card with
        length: Total length of the card number (default 16)
        
    Returns:
        Valid credit card number as string
    """
    # Start with the prefix
    card = prefix
    
    # Generate random digits for all but the last digit
    while len(card) < length - 1:
        card += str(random.randint(0, 9))
    
    # Calculate the last digit to make it valid
    for i in range(10):  # Try digits 0-9
        test_card = card + str(i)
        if luhn_check(test_card):
            return test_card
    
    # Fallback (shouldn't happen)
    return card + "0"

def parse_gen_input(input_text: str) -> Tuple[str, str, str, int, str]:
    """
    Parse the input for the gen command.
    
    Args:
        input_text: Input text after the /gen command
        
    Returns:
        Tuple of (bin_pattern, month, year, amount, cvv)
    """
    # Default values
    bin_pattern = ""
    month = "rnd"
    year = "rnd"
    amount = 10  # Default amount
    cvv = "rnd"
    
    # Check for pipe format first (e.g., 486732|01|24|123|100)
    if "|" in input_text:
        parts = input_text.split("|")
        
        # First part is the BIN/prefix
        if len(parts) > 0:
            bin_pattern = parts[0].strip()
        
        # Second part is the month
        if len(parts) > 1:
            month = parts[1].strip()
            if month.lower() == "rnd":
                month = "rnd"
        
        # Third part is the year
        if len(parts) > 2:
            year = parts[2].strip()
            if year.lower() == "rnd":
                year = "rnd"
            elif len(year) == 4:
                year = year[2:]  # Convert YYYY to YY
        
        # Fourth part is CVV or amount
        if len(parts) > 3:
            part4 = parts[3].strip()
            if part4.lower() == "rnd":
                cvv = "rnd"
            else:
                try:
                    # Check if it's a number (amount)
                    test_amount = int(part4)
                    if test_amount > 0:
                        amount = test_amount
                    else:
                        # If not a positive number, treat as CVV
                        cvv = part4
                except ValueError:
                    # If not a number, treat as CVV
                    cvv = part4
        
        # Fifth part could be amount if CVV was specified
        if len(parts) > 4:
            try:
                test_amount = int(parts[4].strip())
                if test_amount > 0:
                    amount = test_amount
            except ValueError:
                pass
    
    # Check for space-separated format (e.g., 486732 01 24 123 100)
    else:
        parts = input_text.split()
        
        # First part is the BIN/prefix
        if len(parts) > 0:
            bin_pattern = parts[0].strip()
        
        # Second part could be month or amount
        if len(parts) > 1:
            try:
                # Try to parse as amount first
                test_amount = int(parts[1].strip())
                if test_amount > 0:
                    amount = test_amount
                else:
                    month = parts[1].strip()
            except ValueError:
                # Not a number, treat as month
                month = parts[1].strip()
        
        # Third part is year if month was specified
        if len(parts) > 2 and month != "rnd":
            year = parts[2].strip()
            if year.lower() == "rnd":
                year = "rnd"
            elif len(year) == 4:
                year = year[2:]  # Convert YYYY to YY
        
        # Fourth part is CVV if month and year were specified
        if len(parts) > 3 and month != "rnd" and year != "rnd":
            cvv = parts[3].strip()
            if cvv.lower() == "rnd":
                cvv = "rnd"
        
        # Fifth part could be amount if CVV was specified
        if len(parts) > 4:
            try:
                test_amount = int(parts[4].strip())
                if test_amount > 0:
                    amount = test_amount
            except ValueError:
                pass
    
    # Validate bin_pattern - must be at least 6 digits
    if not bin_pattern or len(bin_pattern) < 6:
        raise ValueError("BIN must be at least 6 digits long")
    
    # Return the parsed values
    return bin_pattern, month, year, amount, cvv

async def generate_cards_with_bin_info(bin_pattern: str, month: str, year: str, amount: int, cvv: str) -> Tuple[List[str], Dict]:
    """
    Generate credit cards with BIN information.
    
    Args:
        bin_pattern: BIN or prefix to use for card generation
        month: Expiry month ("rnd" for random or specific month)
        year: Expiry year ("rnd" for random or specific year)
        amount: Number of cards to generate
        cvv: CVV to use ("rnd" for random or specific CVV)
        
    Returns:
        Tuple of (list of generated cards, BIN information)
    """
    # Get BIN information
    bin_number = bin_pattern[:6]
    bin_info = await get_bin_info(bin_number)
    
    # Determine if this is an Amex card
    is_amex = bin_info.get("scheme", "").lower() == "american express" or bin_pattern.startswith(("34", "37"))
    
    # Generate cards
    cards = []
    for _ in range(amount):
        # Generate random month for each card
        if month.lower() == "rnd":
            card_month = str(random.randint(1, 12)).zfill(2)
        else:
            card_month = month
        
        # Generate random year for each card
        if year.lower() == "rnd":
            current_year = time.strftime("%y")
            card_year = str(random.randint(int(current_year), int(current_year) + 7)).zfill(2)
        else:
            card_year = year
        
        # Determine card length based on card type
        card_length = 15 if is_amex else 16
        
        # Generate a valid card number
        card_number = generate_luhn_card(bin_pattern, card_length)
        
        # Generate appropriate CVV based on card type
        if cvv.lower() == "rnd":
            card_cvv = str(random.randint(1000, 9999)) if is_amex else str(random.randint(100, 999))
        else:
            card_cvv = cvv
            # Adjust CVV length based on card type
            if is_amex and len(card_cvv) == 3:
                # For Amex, ensure 4-digit CVV
                card_cvv = card_cvv + str(random.randint(0, 9))
            elif not is_amex and len(card_cvv) == 4:
                # For non-Amex, ensure 3-digit CVV
                card_cvv = card_cvv[:3]
        
        # Format as card|mm|yy|cvv
        card = f"{card_number}|{card_month}|{card_year}|{card_cvv}"
        cards.append(card)
    
    return cards, bin_info

def format_cards_with_bin_info(cards: List[str], bin_info: Dict) -> str:
    """
    Format generated cards with BIN information.
    
    Args:
        cards: List of generated cards
        bin_info: BIN information dictionary
        
    Returns:
        Formatted string with cards and BIN info
    """
    # Extract only the requested BIN information
    brand = (bin_info.get("scheme") or "N/A").title()
    bank = bin_info.get("bank") or "N/A"
    country = bin_info.get("country") or "Unknown"
    card_type = bin_info.get("type", "N/A")
    
    # Create header with status
    header = f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>{len(cards)} 𝘾𝙖𝙧𝙙𝙨</b> ✅</pre>

"""
    
    # Add cards (limit display to 50 for readability)
    display_cards = cards[:50] if len(cards) > 50 else cards
    card_list = "\n".join([f"<code>{card}</code>" for card in display_cards])
    
    # Add note if more cards were generated
    if len(cards) > 50:
        card_list += f"\n\n<code>... and {len(cards) - 50} more cards (sent in file)</code>"
    
    # Create BIN info section at the bottom inside a code block
    bin_info_block = f"""

<pre>┌─ 𝐁𝐢𝐧: {brand}
├─ 𝐁𝐚𝐧𝐤: {bank}
├─ 𝐂𝐨𝐮𝐧𝐭𝐲: {country}
└─ 𝐓𝐨𝐩𝐞: {card_type}</pre>"""
    
    return f"{header}{card_list}{bin_info_block}"

def format_bin_info_for_caption(bin_info: Dict, bin_pattern: str, amount: int) -> str:
    """
    Format BIN information for the file caption.
    
    Args:
        bin_info: BIN information dictionary
        bin_pattern: The BIN pattern used
        amount: Number of cards generated
        
    Returns:
        Formatted string with BIN info for caption
    """
    # Extract BIN information
    brand = (bin_info.get("scheme") or "N/A").title()
    bank = bin_info.get("bank") or "N/A"
    country = bin_info.get("country") or "Unknown"
    card_type = bin_info.get("type", "N/A")
    
    # Format with UI elements
    return f"""<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝐂𝐨𝐦𝐩𝐥𝐞𝐭𝐞</b> ✅</pre>
<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞</b> ↬ <code>{amount}</code> <b>cards</b>
<a href='https://t.me/failfr'>⊀</a> <b>𝐁𝐢𝐧</b> ↬ <code>{bin_pattern[:6]}</code>

<pre>┌─ 𝐁𝐢𝐧: {brand}
├─ 𝐁𝐚𝐧𝐤: {bank}
├─ 𝐂𝐨𝐮𝐧𝐭𝐲: {country}
└─ 𝐓𝐨𝐩𝐞: {card_type}</pre>

<a href='https://t.me/abtlnx'>⌬</a> <b>𝐃𝐞𝐯</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>"""

async def process_generation(user_id: int, bin_pattern: str, month: str, year: str, amount: int, cvv: str, update, context):
    """
    Process card generation in the background.
    
    Args:
        user_id: ID of the user requesting generation
        bin_pattern: BIN or prefix to use for card generation
        month: Expiry month ("rnd" for random or specific month)
        year: Expiry year ("rnd" for random or specific year)
        amount: Number of cards to generate
        cvv: CVV to use ("rnd" for random or specific CVV)
        update: Telegram update object
        context: Telegram context object
    """
    try:
        # Get user credits
        user_credits = get_user_credits(user_id)
        
        # Check if user has enough credits (or unlimited)
        is_unlimited = user_credits == float('inf')
        has_credits = user_credits is not None and (is_unlimited or user_credits > 0)
        
        # If too many cards, send as a file with progress
        if amount > 10:
            # Send initial progress message
            progress_message = await update.message.reply_text(
                f"<pre><a href='https://t.me/failfr'>⩙</a> <b>𝑺𝒕𝒂𝒕𝒖𝒔</b> ↬ <b>𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐢𝐧𝐠</b> ⏳</pre>\n"
                f"<a href='https://t.me/failfr'>⊀</a> <b>𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐢𝐧𝐠</b> ↬ <code>{amount}</code> <b>cards</b>\n"
                f"<a href='https://t.me/failfr'>⊀</a> <b>𝐁𝐢𝐧</b> ↬ <code>{bin_pattern[:6]}</code>\n"
                f"<a href='https://t.me/failfr'>⚠️</a> <i>Generating {amount} cards... This may take a few seconds.</i>",
                parse_mode="HTML"
            )
            
            # Generate cards with BIN info
            cards, bin_info = await generate_cards_with_bin_info(bin_pattern, month, year, amount, cvv)
            
            # Create a file with just the cards (no BIN info inside)
            file_content = chr(10).join(cards)
            
            # Create a file-like object with the requested naming format
            file = io.BytesIO(file_content.encode('utf-8'))
            file.name = f"ChkX_{bin_pattern[:6]}.txt"
            
            # Format the caption with BIN information
            caption = format_bin_info_for_caption(bin_info, bin_pattern, amount)
            
            # Send the file
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                caption=caption,
                parse_mode="HTML"
            )
            
            # Delete the progress message
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=progress_message.message_id
                )
            except Exception as e:
                logger.error(f"Error deleting progress message: {str(e)}")
        else:
            # Generate cards with BIN info
            cards, bin_info = await generate_cards_with_bin_info(bin_pattern, month, year, amount, cvv)
            
            # Format the response
            formatted_response = format_cards_with_bin_info(cards, bin_info)
            
            # Send the cards directly in the message
            await update.message.reply_text(
                text=formatted_response,
                parse_mode="HTML"
            )
        
        # Deduct credits if successful generation and user doesn't have unlimited credits
        if not is_unlimited:
            # Calculate credits to deduct (1 credit per batch, not per card)
            update_user_credits(user_id, -1)
            
            # Get updated credits for response
            updated_credits = get_user_credits(user_id)
            
            # Add warning if credits are now 0
            if updated_credits is not None and updated_credits <= 0:
                # Send warning message
                await update.message.reply_text(
                    f"<a href='https://t.me/failfr'>⚠️</a> <b>𝙒𝙖𝙧𝙣𝙚𝙧𝙖𝙩𝙚</b> <i>You have 0 credits left. Please recharge to continue using this service.</i>",
                    parse_mode="HTML"
                )
        
        logger.info(f"Generated {amount} cards for user {user_id} with BIN {bin_pattern[:6]}")
        
    except Exception as e:
        logger.error(f"Error generating cards for user {user_id}: {str(e)}")
        
        # Send a styled error message
        try:
            await update.message.reply_text(
                text=f"⚠️ <b>Error generating cards. Please try again.</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending error message: {str(e)}")

async def handle_gen_command(update, context):
    """
    Handle the /gen command for generating credit cards.
    
    Args:
        update: Telegram update object
        context: Telegram context object
    """
    # Get user info
    user_id = update.effective_user.id
    
    # Get user tier from plans module
    user_tier = get_user_current_tier(user_id)
    
    # Check cooldown for Trial users only (user-specific)
    current_time = datetime.now()
    if user_tier == "Trial" and user_id in last_command_time:
        time_diff = current_time - last_command_time[user_id]
        if time_diff < timedelta(seconds=10):
            remaining_seconds = 10 - int(time_diff.total_seconds())
            await update.message.reply_text(
                f"⏳ <b>Please wait {remaining_seconds} seconds before using this command again.</b>\n\n"
                f"<i>Upgrade your plan to remove the time limit.</i>",
                parse_mode="HTML"
            )
            return
    
    # Update last command time for this user
    last_command_time[user_id] = current_time
    
    # Get the input text after the command
    input_text = " ".join(context.args)
    
    if not input_text:
        await update.message.reply_text(
            "⚠️ <b>Invalid Format!</b>\n\n"
            "Please provide a valid BIN to generate cards.\n\n"
            "<b>Examples:</b>\n"
            "• <code>/gen 486732</code>\n"
            "• <code>/gen 486732|rnd|rnd|rnd</code> (for random dates and CVV)",
            parse_mode="HTML"
        )
        return
    
    # Parse the input
    try:
        bin_pattern, month, year, amount, cvv = parse_gen_input(input_text)
    except ValueError as e:
        await update.message.reply_text(
            f"⚠️ <b>Error: {str(e)}</b>\n\n"
            "Please provide a valid BIN (at least 6 digits).",
            parse_mode="HTML"
        )
        return
    
    # Start the generation process in the background
    asyncio.create_task(process_generation(user_id, bin_pattern, month, year, amount, cvv, update, context))
