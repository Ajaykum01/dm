import logging
import time
from typing import Dict

from telegram import Update
from telegram.ext import CallbackContext

# Import active mass check dictionaries from each module
from msh import active_mass_checks as msh_active_checks
from mau import active_mass_checks as mau_active_mass_checks

# Import format functions from each module
from msh import format_stopped_response as msh_format_stopped
from mau import format_stopped_response as mau_format_stopped, format_final_response as mau_format_final

logger = logging.getLogger(__name__)

async def handle_stop_command(update: Update, context: CallbackContext):
    """
    Handle /stop command to stop a specific mass check session.
    
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
        user_sessions = []
        
        # Check MSH sessions
        for session_id, data in msh_active_checks.items():
            if data["user_id"] == user_id:
                user_sessions.append(("MSH", session_id))
        
        # Check MSK sessions (Ensure you have msk.py if you use this)
        # from msk import active_mass_checks as msk_active_checks
        # try:
        #     for session_id, data in msk_active_checks.items():
        #         if data["user_id"] == user_id:
        #             user_sessions.append(("MSK", session_id))
        # except: pass
        
        # Check MAU sessions
        for session_id, data in mau_active_mass_checks.items():
            if data["user_id"] == user_id:
                user_sessions.append(("MAU", session_id))
        
        
        if not user_sessions:
            await update.message.reply_text(
                "⚠️ <b>No active mass check sessions found.</b>\n\n"
                "<i>Start a mass check with /msh, /msk, /mau, first.</i>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return
        
        session_list = "\n".join([f"• <code>{module} {session_id}</code>" for module, session_id in user_sessions])
        await update.message.reply_text(
            f"📋 <b>Your active mass check sessions:</b>\n\n"
            f"{session_list}\n\n"
            f"<i>Use /stop &lt;session_id&gt; to stop a specific session.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    session_id = context.args[0].upper()
    
    # Find the session in any of the active check dictionaries
    session_found = False
    session_module = None
    active_dict = None
    format_func = None
    
    # Check MSH sessions
    if session_id in msh_active_checks:
        session_module = "MSH"
        session_found = True
        active_dict = msh_active_checks
        format_func = msh_format_stopped
        
        
    # Check MAU sessions
    elif session_id in mau_active_mass_checks:
        session_module = "MAU"
        session_found = True
        active_dict = mau_active_mass_checks
        format_func = mau_format_final
        
    
    if not session_found:
        await update.message.reply_text(
            f"⚠️ <b>No active mass check session found with ID:</b> <code>{session_id}</code>\n\n"
            "<i>Check session ID and try again.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Check if the user who sent the command is the same as the one who initiated the check
    if active_dict[session_id]["user_id"] != user_id:
        await update.message.reply_text(
            "⛔ <b>Access denied!</b>\n\n"
            "<i>You can only stop your own mass check sessions.</i>",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return
    
    # Set stop flag and event for this session - IMMEDIATE STOP
    active_dict[session_id]["stopped"] = True
    stop_event = active_dict[session_id].get("stop_event")
    if stop_event:
        stop_event.set()
    
    logger.info(f"Stop requested by user {user_id} for {session_module} session {session_id}")
    
    # Cancel all running tasks for this session with immediate effect
    if "workers" in active_dict[session_id]:
        for task in active_dict[session_id]["workers"]:
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled {session_module} task for session {session_id}")
    
    # Calculate elapsed time
    start_time = active_dict[session_id].get("start_time", time.time())
    elapsed_time = round(abs(time.time() - start_time), 2)
    
    # Get stats from active_dict
    stats = active_dict[session_id].get("stats", {
        "total": 0,
        "checked": 0,
        "charged": 0,
        "approved": 0,
        "declined": 0,
        "error": 0
    })
    
    # Get chat_id and message_id
    chat_id = active_dict[session_id].get("chat_id")
    message_id = active_dict[session_id].get("message_id")
    
    # Update progress message to show "Stopped" without stop button
    if chat_id and message_id:
        try:
            # MSH and MPV require session_id in format_stopped, 
            # others (MAU, MSK, MTXT, MST) use format_final_response with stopped=True as 3rd arg
            if session_module in ["MSH", "MPV"]:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=format_func(stats, elapsed_time, first_name, session_id),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            else:
                # MAU, MSK, MTXT, MST use format_final_response with stopped=True
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=format_func(stats, elapsed_time, first_name, True),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
        except Exception as e:
            # If we get a "Message is not modified" error, try to send a new message
            if "Message is not modified" in str(e):
                try:
                    if session_module in ["MSH", "MPV"]:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=format_func(stats, elapsed_time, first_name, session_id),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=format_func(stats, elapsed_time, first_name, True),
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                except Exception as e2:
                    logger.error(f"Error sending {session_module} stop message: {str(e2)}")
            else:
                logger.error(f"Error updating {session_module} stop message: {str(e)}")
    
    # Send confirmation message to user
    await update.message.reply_text(
        f"✅ <b>{session_module} session stopped successfully!</b>\n\n"
        f"<b>Session ID:</b> <code>{session_id}</code>\n"
        f"<b>Cards checked:</b> <code>{stats['checked']}/{stats['total']}</code>\n"
        f"<b>Time elapsed:</b> <code>{elapsed_time}s</code>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    
    # NOTE: DO NOT DELETE from active_dict HERE.
    # The main process function will handle cleanup after its tasks are fully cancelled.
    # This prevents KeyError race condition.
