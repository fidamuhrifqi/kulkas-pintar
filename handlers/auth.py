import asyncio
import logging
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes
from core.config import ALLOWED_USER_IDS

logger = logging.getLogger("kulkas-bot")

_user_locks: dict[int, asyncio.Lock] = {}

def _get_user_lock(user_id: int) -> asyncio.Lock:
    """Get or create an asyncio lock for a specific user."""
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]

def auth_only(func):
    """Decorator: auth check only, no queue/typing. For routing handlers."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            logger.warning("Unauthorized access attempt by user %d", user_id)
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(update, context)
    return wrapper

def authorized(func):
    """Decorator: auth check + typing indicator + per-user request queue."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            logger.warning("Unauthorized access attempt by user %d", user_id)
            await update.message.reply_text("⛔ Unauthorized.")
            return

        lock = _get_user_lock(user_id)

        # If lock is already held, notify user they're queued
        if lock.locked():
            await update.message.reply_text("⏳ Sabar ya, masih proses yang sebelumnya...")

        async with lock:
            # Send typing indicator
            await update.effective_chat.send_action(ChatAction.TYPING)
            return await func(update, context)
    return wrapper
