from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from handlers.auth import auth_only, authorized
from handlers.inventory import cmd_stok
from handlers.recipe import cmd_rekomen, cmd_listrecipe
from services.storage import RECIPES_PATH, load_json

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
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reset — Clear conversation memory."""
    context.user_data["chat_history"] = []
    await update.message.reply_text("🗑️ Memori percakapan sudah direset!")
