"""
Kulkas Pintar — Household Fridge Inventory Telegram Bot
Uses python-telegram-bot v21 + MiniMax API (OpenAI-compatible) + local JSON storage.
"""

import asyncio
import json
import logging
import re
from openai import APITimeoutError, APIConnectionError, APIStatusError
from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_TOKEN,
    MINIMAX_API_KEY,
    ALLOWED_USER_IDS,
    MODEL_LIGHT,
    MODEL_HEAVY,
    CHAT_MEMORY_SIZE,
)
from prompts import (
    SYSTEM_PROMPT_PARSE,
    SYSTEM_PROMPT_PARSE_KELUAR,
    SYSTEM_PROMPT_STOK,
    SYSTEM_PROMPT_REKOMEN,
    SYSTEM_PROMPT_ADDRECIPE,
    SYSTEM_PROMPT_EDITRECIPE,
    SYSTEM_PROMPT_CHAT,
)
from storage import (
    FRIDGE_PATH,
    RECIPES_PATH,
    HISTORY_PATH,
    load_json,
    save_json,
    log_history,
)
from ai_service import call_ai, call_ai_chat, parse_ai_json

# Logging setup
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("kulkas-bot")

# Per-user asyncio locks for request queuing
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

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@authorized
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/menu — Show a reply keyboard with all available commands."""
    keyboard = [
        ["📥 Masuk", "📤 Keluar"],
        ["📦 Stok", "🍳 Rekomen"],
        ["📖 Tambah Resep", "📜 List Resep"],
        ["✏️ Edit Resep"],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, resize_keyboard=True, one_time_keyboard=False
    )
    await update.message.reply_text(
        "📋 *Menu Kulkas Pintar*\n\nPilih perintah di bawah:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

# Map pretty button labels to their command handler functions
MENU_BUTTON_MAP = {
    "📥 Masuk": "masuk",
    "📤 Keluar": "keluar",
    "📦 Stok": "stok",
    "🍳 Rekomen": "rekomen",
    "📖 Tambah Resep": "addrecipe",
    "📜 List Resep": "listrecipe",
    "✏️ Edit Resep": "editrecipe",
}

# Commands that need text input — set pending action instead of executing
PENDING_ACTION_CMDS = {"masuk", "keluar", "addrecipe"}

@auth_only
async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route pretty menu button presses to actual command handlers."""
    text = update.message.text.strip()
    cmd = MENU_BUTTON_MAP.get(text)
    if not cmd:
        return

    # For masuk/keluar, set pending action and prompt for input
    if cmd in PENDING_ACTION_CMDS:
        context.user_data["pending_action"] = cmd
        prompts_dict = {
            "masuk": "📥 Mau masukin apa ke kulkas?\nKetik langsung, contoh: *3 buah tomat, 1 kg ayam*",
            "keluar": "📤 Mau keluarin apa dari kulkas?\nKetik langsung, contoh: *2 buah tomat, 500 gram ayam*",
            "addrecipe": "📖 Mau tambah resep apa?\nKetik nama, bahan, dan langkah.\nContoh: *Nasi Goreng, bahan: nasi 2 piring, telur 2, kecap 3 sdm. Langkah: tumis bawang, masukkan telur, tambah nasi dan kecap*",
        }
        await update.message.reply_text(prompts_dict[cmd], parse_mode="Markdown")
        return

    # Edit resep: show recipe list then enter 2-step edit flow
    if cmd == "editrecipe":
        recipes = load_json(RECIPES_PATH)
        if not recipes:
            await update.message.reply_text("📖 Belum ada resep tersimpan!")
            return
        lines = ["✏️ *Pilih resep yang mau diedit:*\n"]
        for i, r in enumerate(recipes, 1):
            lines.append(f"{i}. {r.get('nama', 'Tanpa Nama')}")
        lines.append("\n↖️ Ketik *nama* atau *nomor* resepnya.")
        context.user_data["pending_action"] = "editrecipe_select"
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # For other commands, execute immediately
    handler_map = {
        "stok": cmd_stok,
        "rekomen": cmd_rekomen,
        "listrecipe": cmd_listrecipe,
    }
    handler = handler_map.get(cmd)
    if handler:
        await handler(update, context)

@authorized
async def cmd_masuk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/masuk [free text] — AI parses items, adds to fridge, logs to history."""
    text = update.message.text.replace("/masuk", "", 1).strip()
    await _process_masuk(update, context, text)

async def _process_masuk(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Core logic for /masuk — parse items and add to fridge."""
    if not text:
        await update.message.reply_text("💡 Contoh: /masuk 3 buah tomat, 1 kg ayam, 2 bungkus mie instan")
        return

    # Ask AI to parse input into structured JSON
    try:
        raw = call_ai(SYSTEM_PROMPT_PARSE, text, model=MODEL_LIGHT)
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    parsed = parse_ai_json(raw)
    if not parsed or "items" not in parsed or not isinstance(parsed["items"], list):
        await update.message.reply_text(
            "❌ Gagal memproses input. Coba ulangi dengan format yang lebih jelas.\n"
            "Contoh: /masuk 3 buah tomat, 1 kg ayam"
        )
        return

    items = parsed["items"]
    fridge = load_json(FRIDGE_PATH)

    # Merge items into fridge (add qty if same name+unit exists)
    for new_item in items:
        nama = new_item.get("nama", "").lower().strip()
        qty = new_item.get("qty", 0)
        satuan = new_item.get("satuan", "pcs").lower().strip()

        if not nama or qty <= 0:
            continue

        # Find existing item with same name and unit
        found = False
        for existing in fridge:
            if existing["nama"] == nama and existing["satuan"] == satuan:
                existing["qty"] += qty
                found = True
                break
        if not found:
            fridge.append({"nama": nama, "qty": qty, "satuan": satuan})

    save_json(FRIDGE_PATH, fridge)
    log_history("masuk", items)

    # Build static confirmation message
    lines = ["✅ *Barang masuk:*"]
    for item in items:
        lines.append(f"  • {item.get('nama', '?')} — {item.get('qty', '?')} {item.get('satuan', 'pcs')}")
    lines.append(f"\n📦 Total jenis di kulkas: {len(fridge)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@authorized
async def cmd_keluar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/keluar [free text] — AI parses items, reduces qty in fridge, logs to history."""
    text = update.message.text.replace("/keluar", "", 1).strip()
    await _process_keluar(update, context, text)

async def _process_keluar(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Core logic for /keluar — parse items and remove from fridge."""
    if not text:
        await update.message.reply_text("💡 Contoh: /keluar 2 buah tomat, 500 gram ayam")
        return

    fridge = load_json(FRIDGE_PATH)
    fridge_text = json.dumps(fridge, ensure_ascii=False)
    
    prompt = SYSTEM_PROMPT_PARSE_KELUAR + f"\n\nCURRENT FRIDGE INVENTORY:\n{fridge_text}"

    # Ask AI to parse input into structured JSON
    try:
        raw = call_ai(prompt, text, model=MODEL_HEAVY)
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    parsed = parse_ai_json(raw)
    if not parsed or "items" not in parsed or not isinstance(parsed["items"], list):
        await update.message.reply_text(
            "❌ Gagal memproses input. Coba ulangi dengan format yang lebih jelas.\n"
            "Contoh: /keluar 2 buah tomat"
        )
        return

    items = parsed["items"]
    results = []

    for out_item in items:
        nama = out_item.get("nama", "").lower().strip()
        qty = out_item.get("qty", 0)
        satuan = out_item.get("satuan", "pcs").lower().strip()

        if not nama or qty <= 0:
            continue

        # Find matching item in fridge
        found = False
        for existing in fridge:
            # Cari berdasarkan nama saja (hiraukan satuan) agar lebih fleksibel saat barang keluar
            if existing["nama"] == nama:
                existing["qty"] -= qty
                if existing["qty"] <= 0:
                    fridge.remove(existing)
                    results.append(f"  • {nama} — habis, dihapus dari kulkas")
                else:
                    results.append(f"  • {nama} — sisa {existing['qty']} {existing['satuan']}")
                found = True
                break

        if not found:
            results.append(f"  • {nama} — tidak ditemukan di kulkas")

    save_json(FRIDGE_PATH, fridge)
    log_history("keluar", items)

    # Build static confirmation message
    lines = ["✅ *Barang keluar:*"] + results
    lines.append(f"\n📦 Total jenis di kulkas: {len(fridge)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@authorized
async def cmd_stok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stok — AI formats fridge contents into a categorized, readable list."""
    fridge = load_json(FRIDGE_PATH)

    if not fridge:
        await update.message.reply_text("🫙 Kulkas kosong! Pakai /masuk untuk menambahkan bahan.")
        return

    fridge_text = json.dumps(fridge, ensure_ascii=False)

    try:
        reply = call_ai(SYSTEM_PROMPT_STOK, f"Isi kulkas saat ini:\n{fridge_text}", model=MODEL_LIGHT)
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    await update.message.reply_text(reply)

@authorized
async def cmd_rekomen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rekomen — AI recommends 2-3 meals using a portion of fridge inventory."""
    fridge = load_json(FRIDGE_PATH)

    if not fridge:
        await update.message.reply_text("🫙 Kulkas kosong! Pakai /masuk untuk menambahkan bahan dulu.")
        return

    fridge_text = json.dumps(fridge, ensure_ascii=False)

    try:
        reply = call_ai(
            SYSTEM_PROMPT_REKOMEN,
            f"Isi kulkas saat ini (ini inventaris, bukan daftar belanja satu kali masak):\n{fridge_text}",
            model=MODEL_HEAVY,
        )
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    await update.message.reply_text(reply)

@authorized
async def cmd_addrecipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addrecipe [free text] — AI parses recipe into structured JSON and saves."""
    text = update.message.text.replace("/addrecipe", "", 1).strip()
    await _process_addrecipe(update, context, text)

async def _process_addrecipe(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Core logic for /addrecipe — parse recipe and save."""
    if not text:
        await update.message.reply_text(
            "💡 Contoh: /addrecipe Nasi Goreng\n"
            "Bahan: 1 piring nasi, 2 butir telur, 3 siung bawang putih, kecap secukupnya\n"
            "Langkah: Tumis bawang, masukkan telur, aduk rata, masukkan nasi, tambah kecap, aduk hingga matang"
        )
        return

    # Ask AI to parse recipe into structured JSON
    try:
        raw = call_ai(SYSTEM_PROMPT_ADDRECIPE, text, model=MODEL_HEAVY)
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    parsed = parse_ai_json(raw)
    if not parsed or "nama" not in parsed:
        await update.message.reply_text(
            "❌ Gagal memproses resep. Coba tulis dengan format yang lebih jelas.\n"
            "Sertakan nama resep, bahan-bahan, dan langkah memasak."
        )
        return

    recipes = load_json(RECIPES_PATH)
    recipes.append(parsed)
    save_json(RECIPES_PATH, recipes)

    recipe_name = parsed.get("nama", "Tanpa Nama")
    ingredient_count = len(parsed.get("bahan", []))
    step_count = len(parsed.get("langkah", []))

    await update.message.reply_text(
        f"✅ *Resep disimpan!*\n\n"
        f"📖 {recipe_name}\n"
        f"🥘 {ingredient_count} bahan\n"
        f"📝 {step_count} langkah",
        parse_mode="Markdown",
    )

# ---------------------------------------------------------------------------
# Free-text handler (casual cooking chat, no JSON access)
# ---------------------------------------------------------------------------

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

@authorized
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset — Clear conversation memory."""
    context.user_data["chat_history"] = []
    await update.message.reply_text("🗑️ Memori percakapan sudah direset!")

async def _view_recipe_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Show full recipe detail by name or number."""
    recipes = load_json(RECIPES_PATH)
    if not recipes:
        await update.message.reply_text("📖 Belum ada resep tersimpan.")
        return

    recipe = None

    # Try matching by number first
    try:
        idx = int(text.strip()) - 1
        if 0 <= idx < len(recipes):
            recipe = recipes[idx]
    except ValueError:
        pass

    # Try matching by name (case-insensitive partial match)
    if not recipe:
        query = text.strip().lower()
        for r in recipes:
            if query in r.get("nama", "").lower():
                recipe = r
                break

    if not recipe:
        await update.message.reply_text(
            f"❌ Resep \"{text}\" tidak ditemukan.\n"
            "Coba ketik /resep untuk lihat daftar resep."
        )
        return

    # Format full recipe detail
    nama = recipe.get("nama", "Tanpa Nama")
    lines = [f"📖 *{nama}*\n"]

    bahan = recipe.get("bahan", [])
    if bahan:
        lines.append("🥘 *Bahan:*")
        for b in bahan:
            lines.append(f"  • {b.get('nama', '?')} — {b.get('qty', '?')} {b.get('satuan', '')}")
        lines.append("")

    langkah = recipe.get("langkah", [])
    if langkah:
        lines.append("📝 *Langkah:*")
        for i, step in enumerate(langkah, 1):
            lines.append(f"  {i}. {step}")

    link = recipe.get("link")
    if link:
        lines.append(f"\n🔗 *Link:* [Lihat Resep]({link})")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def _editrecipe_select(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Step 1 of edit: User selects which recipe to edit."""
    recipes = load_json(RECIPES_PATH)
    if not recipes:
        await update.message.reply_text("📖 Belum ada resep tersimpan.")
        return

    recipe = None
    recipe_idx = -1

    try:
        idx = int(text.strip()) - 1
        if 0 <= idx < len(recipes):
            recipe = recipes[idx]
            recipe_idx = idx
    except ValueError:
        pass

    if not recipe:
        query = text.strip().lower()
        for i, r in enumerate(recipes):
            if query in r.get("nama", "").lower():
                recipe = r
                recipe_idx = i
                break

    if not recipe:
        await update.message.reply_text(
            f"❌ Resep \"{text}\" tidak ditemukan.\n"
            "Coba ketik /menu lalu Edit Resep lagi."
        )
        return

    # Store the selected recipe index
    context.user_data["editrecipe_idx"] = recipe_idx
    context.user_data["pending_action"] = "editrecipe_edit"

    # Format full recipe detail to show to user
    nama = recipe.get("nama", "Tanpa Nama")
    lines = [f"✏️ *Edit Resep:* {nama}\n"]

    bahan = recipe.get("bahan", [])
    if bahan:
        lines.append("🥘 *Bahan saat ini:*")
        for b in bahan:
            lines.append(f"  • {b.get('nama', '?')} — {b.get('qty', '?')} {b.get('satuan', '')}")
        lines.append("")

    langkah = recipe.get("langkah", [])
    if langkah:
        lines.append("📝 *Langkah saat ini:*")
        for i, step in enumerate(langkah, 1):
            lines.append(f"  {i}. {step}")
            
    link = recipe.get("link")
    if link:
        lines.append(f"\n🔗 *Link:* [Lihat Resep]({link})")

    lines.append("\n=====================\n")
    lines.append("Apa yang mau diubah? Ketik instruksinya.")
    lines.append("Contoh: *Ganti ayam dengan sapi, hapus tomat, tambahkan kecap 2 sdm*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def _editrecipe_apply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Step 2 of edit: AI processes the edit instructions and saves."""
    recipe_idx = context.user_data.get("editrecipe_idx")
    if recipe_idx is None:
        await update.message.reply_text("❌ Gagal menemukan resep yang mau diedit. Mulai ulang dari /menu.")
        return

    recipes = load_json(RECIPES_PATH)
    if not (0 <= recipe_idx < len(recipes)):
        await update.message.reply_text("❌ Resep tidak valid. Mulai ulang dari /menu.")
        return

    current_recipe = recipes[recipe_idx]
    recipe_text = json.dumps(current_recipe, ensure_ascii=False)

    try:
        raw = call_ai(
            SYSTEM_PROMPT_EDITRECIPE,
            f"Current Recipe:\n{recipe_text}\n\nUser Instruction:\n{text}",
            model=MODEL_HEAVY
        )
    except (APITimeoutError, APIConnectionError, APIStatusError):
        await update.message.reply_text("⚠️ Gagal menghubungi AI. Coba lagi nanti ya.")
        return

    parsed = parse_ai_json(raw)
    if not parsed or "nama" not in parsed:
        await update.message.reply_text("❌ Gagal memproses perubahan resep. Coba instruksi yang lebih jelas.")
        return

    # Update recipe and save
    recipes[recipe_idx] = parsed
    save_json(RECIPES_PATH, recipes)

    # Clean up state
    del context.user_data["editrecipe_idx"]

    await update.message.reply_text(f"✅ Resep *{parsed.get('nama')}* berhasil diupdate!", parse_mode="Markdown")

@authorized
async def cmd_listrecipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resep — Display recipe names and prompt user to pick one."""
    recipes = load_json(RECIPES_PATH)

    if not recipes:
        await update.message.reply_text("📖 Belum ada resep tersimpan! Pakai /addrecipe untuk menambahkan.")
        return

    lines = ["📜 *Daftar Resep:*\n"]
    for i, recipe in enumerate(recipes, 1):
        nama = recipe.get("nama", "Tanpa Nama")
        lines.append(f"{i}. {nama}")
    lines.append("\n↖️ Ketik *nama* atau *nomor* resep untuk lihat detailnya.")

    context.user_data["pending_action"] = "viewrecipe"
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

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
