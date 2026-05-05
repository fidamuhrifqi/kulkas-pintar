"""
Kulkas Pintar — Household Fridge Inventory Telegram Bot
Uses python-telegram-bot v21 + MiniMax API (OpenAI-compatible) + local JSON storage.
"""

import asyncio
import logging
import re
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from core.config import TELEGRAM_TOKEN, MINIMAX_API_KEY, ALLOWED_USER_IDS
from services.storage import FRIDGE_PATH, RECIPES_PATH, HISTORY_PATH, save_json

from handlers.menu import cmd_menu, handle_menu_button, cmd_reset, MENU_BUTTON_MAP
from handlers.inventory import cmd_masuk, cmd_keluar, cmd_stok
from handlers.recipe import cmd_rekomen, cmd_addrecipe, cmd_listrecipe
from handlers.chat import handle_free_text

# Logging setup
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("kulkas-bot")

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the bot."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN is not set in .env")
        return
    if not MINIMAX_API_KEY:
        logger.error("MINIMAX_API_KEY is not set in .env")
        return
    if not ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS is empty — no one can use the bot!")

    logger.info("Starting Kulkas Pintar Bot...")
    logger.info("Allowed user IDs: %s", ALLOWED_USER_IDS)

    # Ensure JSON files exist
    for path in [FRIDGE_PATH, RECIPES_PATH, HISTORY_PATH]:
        if not path.exists():
            save_json(path, [])

    # Python 3.14+ requires explicit event loop creation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("masuk", cmd_masuk))
    app.add_handler(CommandHandler("keluar", cmd_keluar))
    app.add_handler(CommandHandler("stok", cmd_stok))
    app.add_handler(CommandHandler("rekomen", cmd_rekomen))
    app.add_handler(CommandHandler("addrecipe", cmd_addrecipe))
    app.add_handler(CommandHandler("resep", cmd_listrecipe))
    app.add_handler(CommandHandler("reset", cmd_reset))

    # Menu button handler (must be before free-text handler)
    menu_button_filter = filters.TEXT & filters.Regex(
        "^(" + "|".join(re.escape(k) for k in MENU_BUTTON_MAP) + ")$"
    )
    app.add_handler(MessageHandler(menu_button_filter, handle_menu_button))

    # Free-text handler (must be added last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    # Start polling
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
