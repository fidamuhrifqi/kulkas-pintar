import json
from openai import APITimeoutError, APIConnectionError, APIStatusError
from telegram import Update
from telegram.ext import ContextTypes

from handlers.auth import authorized
from core.config import MODEL_LIGHT, MODEL_HEAVY
from core.prompts import SYSTEM_PROMPT_PARSE, SYSTEM_PROMPT_PARSE_KELUAR, SYSTEM_PROMPT_STOK
from services.storage import FRIDGE_PATH, load_json, save_json, log_history
from services.ai_service import call_ai, parse_ai_json

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
