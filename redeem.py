import logging
import random
import string
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from database import get_or_create_user, update_user_plan, get_user_plan, get_user_credits, save_redeem_code, get_redeem_code_info, mark_redeem_code_as_used, has_user_active_plan
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# List of admin user IDs who can use plan commands
ADMIN_IDS = [7758558590]  # Replace with your actual admin ID(s)

# Plan configurations
PLANS = {
    "plan1": {
        "name": "Core Access",
        "tier": "Core",
        "duration_days": 7,
        "emoji": "🛠️"
    },
    "plan2": {
        "name": "Elite Access",
        "tier": "Elite",
        "duration_days": 15,
        "emoji": "👑"
    },
    "plan3": {
        "name": "Root Access",
        "tier": "Root",
        "duration_days": 30,
        "emoji": "⭐"
    },
    "plan4": {
        "name": "X-Access",
        "tier": "X",
        "duration_days": 90,
        "emoji": "💎"
    }
}

# Dictionary to store background tasks
background_tasks = {}

# Dictionary to track active requests per user (to prevent spamming)
active_requests = {}

def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in ADMIN_IDS

def generate_redeem_code(length: int = 16) -> str:
    """Generate a random redeem code starting with CXGFT-."""
    # Generate random characters after CXGFT-
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(random.choices(chars, k=length - 5))  # 5 for CXGFT-
    return f"CXGFT-{random_part}"

async def generate_redeem_codes_background(update, context, plan_type: str, count: int):
    """
    Generate redeem codes in background.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        plan_type: Type of plan (plan1, plan2, etc.)
        count: Number of codes to generate
    """
    try:
        plan_info = PLANS.get(plan_type)
        if not plan_info:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/failfr'>❌</a> <b>Error</b></pre>
<a href='https://t.me/failfr'>⊀</a> <b>Response</b> ↬ <code>Invalid plan type</code>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Generate codes
        codes = []
        for i in range(count):
            # Add progress indicator for large batches
            if count > 10 and i % 5 == 0:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=background_tasks[update.effective_user.id]["message_id"],
                        text=f"""<pre>🔄 <b>Generating Redeem Codes...</b></pre>
<pre>Creating {count} codes for {plan_info["name"]}...</pre>
<a href='https://t.me/failfr'>⊀</a> <b>Status</b> ↬ <i>Progress: {i+1}/{count} codes generated</i>""",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error updating progress message: {e}")
            
            code = generate_redeem_code()
            # Store in database
            save_redeem_code(code, plan_info["tier"], plan_info["duration_days"])
            codes.append(code)
        
        # Format response with styled codes
        codes_text = ""
        for i, code in enumerate(codes):
            if i % 2 == 0:  # Alternate styling for better visual
                codes_text += f"<a href='https://t.me/failfr'>⬜</a> <code>{code}</code>\n"
            else:
                codes_text += f"<a href='https://t.me/failfr'>⬛</a> <code>{code}</code>\n"
        
        # Update message with generated codes
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=background_tasks[update.effective_user.id]["message_id"],
            text=f"""<pre><a href='https://t.me/failfr'>✅</a> <b>Redeem Codes Generated</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Plan</b> ↬ {plan_info["emoji"]} {plan_info["name"]}
<a href='https://t.me/failfr'>⊀</a> <b>Tier</b> ↬ <code>{plan_info["tier"]}</code>
<a href='https://t.me/failfr'>⊀</a> <b>Duration</b> ↬ <code>{plan_info["duration_days"]} days</code>
<a href='https://t.me/failfr'>⊀</a> <b>Codes Generated</b> ↬ <code>{count}</code>

<a href='https://t.me/abtlnx'>⊚</a> <b>Generated Codes</b>
{codes_text}
<a href='https://t.me/abtlnx'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
            parse_mode=ParseMode.HTML
        )
        
        # Log generation
        logger.info(f"Generated {count} redeem codes for {plan_info['name']} by admin {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error generating redeem codes: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/failfr'>❌</a> <b>Error</b></pre>
<a href='https://t.me/failfr'>⊀</a> <b>Response</b> ↬ <code>{str(e)}</code>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failedfr'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")
    
    finally:
        # Remove task from background tasks dictionary
        if update.effective_user.id in background_tasks:
            del background_tasks[update.effective_user.id]
        # Mark user as no longer having an active request
        if update.effective_user.id in active_requests:
            active_requests[update.effective_user.id] = False

async def generate_credits_codes_background(update, context, count: int):
    """
    Generate redeem codes with 100 credits in background.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        count: Number of codes to generate
    """
    try:
        # Generate codes
        codes = []
        for i in range(count):
            # Add progress indicator for large batches
            if count > 10 and i % 5 == 0:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=background_tasks[update.effective_user.id]["message_id"],
                        text=f"""<pre>🔄 <b>Generating Credits Codes...</b></pre>
<pre>Creating {count} codes with 100 credits each...</pre>
<a href='https://t.me/failfr'>⊀</a> <b>Status</b> ↬ <i>Progress: {i+1}/{count} codes generated</i>""",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Error updating progress message: {e}")
            
            code = generate_redeem_code()
            # Store in database with 100 credits (special tier)
            save_redeem_code(code, "Credits", 0)  # 0 duration means 100 credits
            codes.append(code)
        
        # Format response with styled codes
        codes_text = ""
        for i, code in enumerate(codes):
            if i % 2 == 0:  # Alternate styling for better visual
                codes_text += f"<a href='https://t.me/failfr'>⬜</a> <code>{code}</code>\n"
            else:
                codes_text += f"<a href='https://t.me/failfr'>⬛</a> <code>{code}</code>\n"
        
        # Update message with generated codes
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=background_tasks[update.effective_user.id]["message_id"],
            text=f"""<pre><a href='https://t.me/failfr'>✅</a> <b>Credits Codes Generated</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Type</b> ↬ <code>100 Credits</code>
<a href='https://t.me/failfr'>⊀</a> <b>Codes Generated</b> ↬ <code>{count}</code>

<a href='https://t.me/failfr'>⊚</a> <b>Generated Codes</b>
{codes_text}
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
            parse_mode=ParseMode.HTML
        )
        
        # Log generation
        logger.info(f"Generated {count} credits codes by admin {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error generating credits codes: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/abtlnx'>❌</a> <b>Error</b></pre>
<a href='https://t.me/abtlnx'>⊀</a> <b>Response</b> ↬ <code>{str(e)}</code>
<a href='https://t.me/abtlnx'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")
    
    finally:
        # Remove task from background tasks dictionary
        if update.effective_user.id in background_tasks:
            del background_tasks[update.effective_user.id]
        # Mark user as no longer having an active request
        if update.effective_user.id in active_requests:
            active_requests[update.effective_user.id] = False

async def handle_gplan_command(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_type: str):
    """Handle /gplan commands to generate redeem codes."""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n\n"
            "<i>You don't have permission to use this command.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user already has an active request (to prevent spamming)
    if update.effective_user.id in active_requests and active_requests[update.effective_user.id]:
        await update.message.reply_text(
            "⏳ <b>Please wait for your current request to complete before sending another one.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if count was provided
    if not context.args:
        await update.message.reply_text(
            f"<pre>⚠️ <b>Missing Count</b></pre>\n\n"
            f"<i>Usage: /{plan_type} 5 (to generate 5 codes)</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get count from command
    try:
        count = int(context.args[0])
        if count <= 0 or count > 50:  # Limit to prevent abuse
            await update.message.reply_text(
                "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
                "<i>Please provide a number between 1 and 50.</i>",
                parse_mode=ParseMode.HTML
            )
            return
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
            "<i>Please provide a valid number.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if there's already a background task running for this user
    if update.effective_user.id in background_tasks:
        await update.message.reply_text(
            "<pre>⚠️ <b>Already Processing</b></pre>\n\n"
            "<i>Please wait for current operation to complete.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mark this user as having an active request
    active_requests[update.effective_user.id] = True
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>Generating Redeem Codes...</b></pre>
<pre>Creating {count} codes for {PLANS[plan_type]['name']}...</pre>
<a href='https://t.me/abtlnx'>⊀</a> <b>Status</b> ↬ <i>Processing in background</i>""",
        parse_mode=ParseMode.HTML
    )
    
    # Store message ID for later editing
    background_tasks[update.effective_user.id] = {
        "message_id": processing_message.message_id
    }
    
    # Create and start background task
    task = asyncio.create_task(generate_redeem_codes_background(update, context, plan_type, count))
    background_tasks[update.effective_user.id]["task"] = task

async def handle_gcodes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /gcodes command to generate credits codes."""
    # Check if user is admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "<pre>⚠️ <b>Access Denied</b></pre>\n\n"
            "<i>You don't have permission to use this command.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if user already has an active request (to prevent spamming)
    if update.effective_user.id in active_requests and active_requests[update.effective_user.id]:
        await update.message.reply_text(
            "⏳ <b>Please wait for your current request to complete before sending another one.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if count was provided
    if not context.args:
        await update.message.reply_text(
            "<pre>⚠️ <b>Missing Count</b></pre>\n\n"
            "<i>Usage: /gcodes 5 (to generate 5 codes)</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get count from command
    try:
        count = int(context.args[0])
        if count <= 0 or count > 50:  # Limit to prevent abuse
            await update.message.reply_text(
                "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
                "<i>Please provide a number between 1 and 50.</i>",
                parse_mode=ParseMode.HTML
            )
            return
    except ValueError:
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Count</b></pre>\n\n"
            "<i>Please provide a valid number.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if there's already a background task running for this user
    if update.effective_user.id in background_tasks:
        await update.message.reply_text(
            "<pre>⚠️ <b>Already Processing</b></pre>\n\n"
            "<i>Please wait for current operation to complete.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mark this user as having an active request
    active_requests[update.effective_user.id] = True
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>Generating Credits Codes...</b></pre>
<pre>Creating {count} codes with 100 credits each...</pre>
<a href='https://t.me/abtlnx'>⊀</a> <b>Status</b> ↬ <i>Processing in background</i>""",
        parse_mode=ParseMode.HTML
    )
    
    # Store message ID for later editing
    background_tasks[update.effective_user.id] = {
        "message_id": processing_message.message_id
    }
    
    # Create and start background task
    task = asyncio.create_task(generate_credits_codes_background(update, context, count))
    background_tasks[update.effective_user.id]["task"] = task

async def handle_claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /claim command to redeem a code."""
    # Check if a code was provided
    if not context.args:
        await update.message.reply_text(
            "<pre>⚠️ <b>Missing Code</b></pre>\n\n"
            "<i>Usage: /claim CXGFT-ABC123DEF456</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get code from command
    code = context.args[0].strip()
    
    # Validate code format (must start with CXGFT-)
    if not code.startswith("CXGFT-"):
        await update.message.reply_text(
            "<pre>⚠️ <b>Invalid Code Format</b></pre>\n\n"
            "<i>Redeem codes must start with CXGFT-.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Get user info
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    # Check if user already has an active request (to prevent spamming)
    if user_id in active_requests and active_requests[user_id]:
        await update.message.reply_text(
            "⏳ <b>Please wait for your current request to complete before sending another one.</b>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Check if there's already a background task running for this user
    if user_id in background_tasks:
        await update.message.reply_text(
            "<pre>⚠️ <b>Already Processing</b></pre>\n\n"
            "<i>Please wait for current operation to complete.</i>",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Mark this user as having an active request
    active_requests[user_id] = True
    
    # Send a processing message
    processing_message = await update.message.reply_text(
        f"""<pre>🔄 <b>Validating Redeem Code...</b></pre>
<pre>Checking code: {code}</pre>
<a href='https://t.me/abtlnx'>⊀</a> <b>Status</b> ↬ <i>Processing in background</i>""",
        parse_mode=ParseMode.HTML
    )
    
    # Store message ID for later editing
    background_tasks[user_id] = {
        "message_id": processing_message.message_id
    }
    
    # Create and start background task
    task = asyncio.create_task(claim_redeem_code_background(update, context, code))
    background_tasks[user_id]["task"] = task

async def claim_redeem_code_background(update, context, code):
    """
    Process redeem code in background.
    
    Args:
        update: Telegram update object
        context: Telegram context object
        code: Redeem code to process
    """
    try:
        # Check if code exists in database
        code_info = get_redeem_code_info(code)
        
        if not code_info:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/abtlnx'>❌</a> <b>Invalid Code</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/failfr'>⊀</a> <b>Response</b> ↬ <code>This redeem code is invalid or has already been used.</code>
<a href='https://t.me/failfr'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Get plan details from code info
        tier = code_info["tier"]
        duration_days = code_info["duration_days"]
        
        # Handle credits codes (special tier)
        if tier == "Credits":
            # Add 100 credits to user
            from database import update_user_credits
            update_user_credits(update.effective_user.id, 100)
            
            # Mark code as used in database
            mark_redeem_code_as_used(code, update.effective_user.id)
            
            # Format success message
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/abtlnx'>✅</a> <b>Code Redeemed Successfully</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/failfr'>⊀</a> <b>Type</b> ↬ <code>100 Credits</code>
<a href='https://t.me/failfr'>⊀</a> <b>Credits Added</b> ↬ <code>+100</code>

<a href='https://t.me/failfr'>ℭ</a> <b>Benefits:</b> <i>100 credits added to your account</i>
<a href='https://t.me/failfr'>ℭ</a> <b>Access:</b> <i>Use these credits for any command</i>

<a href='https://t.me/failfr'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
            
            # Log redemption
            logger.info(f"User {update.effective_user.id} redeemed credits code {code}")
            return
        
        # Check if user has an active plan
        user_has_active_plan = has_user_active_plan(update.effective_user.id)
        
        # Find plan info for regular plans
        plan_info = None
        for plan_id, info in PLANS.items():
            if info["tier"] == tier:
                plan_info = info
                break
        
        if not plan_info:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/abtlnx'>❌</a> <b>Invalid Plan</b></pre>

<a href='https://t.me/abtlnx'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/abtlnx'>⊀</a> <b>Response</b> ↬ <code>This code is for an invalid plan.</code>
<a href='https://t.me/abtlnx'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/abtlnx'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failedfr'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # If user has an active plan, don't allow redeeming another plan
        if user_has_active_plan:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/abtlnx'>❌</a> <b>Redemption Failed</b></pre>

<a href='https://t.me/abtlnx'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/abtlnx'>⊀</a> <b>Response</b> ↬ <code>You already have an active plan. You cannot redeem another plan while your current plan is active.</code>
<a href='https://t.me/abtlnx'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/abtlnx'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Calculate expiry date
        expiry_date = datetime.now() + timedelta(days=duration_days)
        
        # Update user plan in database
        success = update_user_plan(update.effective_user.id, tier, expiry_date)
        
        if success:
            # Mark code as used in database
            mark_redeem_code_as_used(code, update.effective_user.id)
            
            # Format success message
            expiry_formatted = expiry_date.strftime('%Y-%m-%d %H:%M:%S')
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/abtlnx'>✅</a> <b>Code Redeemed Successfully</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/failfr'>⊀</a> <b>Plan</b> ↬ {plan_info["emoji"]} {plan_info["name"]}
<a href='https://t.me/failfr'>⊀</a> <b>Tier</b> ↬ <code>{tier}</code>
<a href='https://t.me/failfr'>⊀</a> <b>Duration</b> ↬ <code>{duration_days} days</code>
<a href='https://t.me/failfr'>⊀</a> <b>Expires</b> ↬ <code>{expiry_formatted}</code>

<a href='https://t.me/failfr'>ℭ</a> <b>Benefits:</b> <i>Unlimited credits until plan ends</i>
<a href='https://t.me/failfr'>ℭ</a> <b>Access:</b> <i>No cooldowns on any commands</i>

<a href='https://t.me/failfr'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
            
            # Log redemption
            logger.info(f"User {update.effective_user.id} redeemed code {code} for {plan_info['name']}")
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/failfr'>❌</a> <b>Redemption Failed</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Code</b> ↬ <code>{code}</code>
<a href='https://t.me/failfr'>⊀</a> <b>Response</b> ↬ <code>Failed to update your plan. Please try again later.</code>
<a href='https://t.me/failfr'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Error claiming redeem code: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=background_tasks[update.effective_user.id]["message_id"],
                text=f"""<pre><a href='https://t.me/failfr'>❌</a> <b>Error</b></pre>

<a href='https://t.me/failfr'>⊀</a> <b>Response</b> ↬ <code>{str(e)}</code>
<a href='https://t.me/failfr'>⌬</a> <b>User</b> ↬ <a href='tg://user?id={update.effective_user.id}'>{update.effective_user.first_name}</a>
<a href='https://t.me/failfr'>⌬</a> <b>Dev</b> ↬ <a href='https://t.me/failurefr_07'>kคli liຖนxx</a>""",
                parse_mode=ParseMode.HTML
            )
        except Exception as e2:
            logger.error(f"Error sending error message: {e2}")
    
    finally:
        # Remove task from background tasks dictionary
        if update.effective_user.id in background_tasks:
            del background_tasks[update.effective_user.id]
        # Mark user as no longer having an active request
        if update.effective_user.id in active_requests:
            active_requests[update.effective_user.id] = False

# Individual command handlers
async def handle_gplan1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan1")

async def handle_gplan2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan2")

async def handle_gplan3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan3")

async def handle_gplan4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gplan_command(update, context, "plan4")

async def handle_gcodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_gcodes_command(update, context)

async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_claim_command(update, context)
