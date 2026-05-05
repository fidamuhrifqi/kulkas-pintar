import json
from openai import APITimeoutError, APIConnectionError, APIStatusError
from telegram import Update
from telegram.ext import ContextTypes

from handlers.auth import authorized
from core.config import MODEL_HEAVY, CHAT_MEMORY_SIZE
from core.prompts import SYSTEM_PROMPT_CHAT
from services.storage import FRIDGE_PATH, RECIPES_PATH, load_json
from services.ai_service import call_ai_chat

from handlers.inventory import _process_masuk, _process_keluar
from handlers.recipe import _process_addrecipe, _view_recipe_detail, _editrecipe_select, _editrecipe_apply

@authorized
async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle non-command text: pending actions first, then casual chat with memory."""
    text = update.message.text.strip()
    if not text:
        return

    # Check if there's a pending action from menu button tap
    pending = context.user_data.get("pending_action")
    if pending:
        context.user_data["pending_action"] = None  # Clear immediately
        if pending == "masuk":
            await _process_masuk(update, context, text)
            return
        elif pending == "keluar":
            await _process_keluar(update, context, text)
            return
        elif pending == "addrecipe":
            await _process_addrecipe(update, context, text)
            return
        elif pending == "viewrecipe":
            await _view_recipe_detail(update, context, text)
            return
        elif pending == "editrecipe_select":
            await _editrecipe_select(update, context, text)
            return
        elif pending == "editrecipe_edit":
            await _editrecipe_apply(update, context, text)
            return

    # Initialize chat history in user_data if not present
    if "chat_history" not in context.user_data:
        context.user_data["chat_history"] = []

    history = context.user_data["chat_history"]

    # Build dynamic system prompt with current fridge & recipes data
    fridge = load_json(FRIDGE_PATH)
    recipes = load_json(RECIPES_PATH)

    dynamic_prompt = SYSTEM_PROMPT_CHAT
    if fridge:
        dynamic_prompt += f"\n\n📦 ISI KULKAS SAAT INI:\n{json.dumps(fridge, ensure_ascii=False)}"
    else:
        dynamic_prompt += "\n\n📦 ISI KULKAS: Kosong."
    if recipes:
        dynamic_prompt += f"\n\n📖 DAFTAR RESEP TERSIMPAN:\n{json.dumps(recipes, ensure_ascii=False)}"

    try:
        reply = call_ai_chat(dynamic_prompt, text, history, model=MODEL_HEAVY)
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    # Append the exchange to history
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})

    # Trim history to max size (each pair = 2 entries)
    max_entries = CHAT_MEMORY_SIZE * 2
    if len(history) > max_entries:
        context.user_data["chat_history"] = history[-max_entries:]

    await update.message.reply_text(reply)
