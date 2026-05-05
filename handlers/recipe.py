import json
from openai import APITimeoutError, APIConnectionError, APIStatusError
from telegram import Update
from telegram.ext import ContextTypes

from handlers.auth import authorized
from core.config import MODEL_LIGHT, MODEL_HEAVY
from core.prompts import SYSTEM_PROMPT_REKOMEN, SYSTEM_PROMPT_ADDRECIPE, SYSTEM_PROMPT_EDITRECIPE
from services.storage import FRIDGE_PATH, RECIPES_PATH, load_json, save_json
from services.ai_service import call_ai, parse_ai_json

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
