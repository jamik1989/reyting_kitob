from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import ContextTypes, ConversationHandler

from ..config import CONFIRM_CHAT_ID
from ..services.moysklad import (
    search_products,
    get_product_by_id,
    get_default_organization,
    create_customerorder,
    find_store_meta_by_name,
)

TK_SEARCH, TK_PICK, TK_EXTRA, TK_QTY, TK_REVIEW, TK_EDIT_VALUE = range(6)

TG_TZ = ZoneInfo(os.getenv("TG_TZ", "Asia/Tashkent"))
MS_TZ = ZoneInfo(os.getenv("MOYSKLAD_TZ", "Europe/Moscow"))

CONFIRM_STORE_NAME = "Abusahiy 75"


def _menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton("/tasdiq"), KeyboardButton("/takror")]],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=True,
    )


def _fmt_num(n: Optional[int]) -> str:
    if not isinstance(n, int):
        return "N/A"
    return f"{n:,}".replace(",", " ")


def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _normalize_size(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.replace("х", "x").replace("*", "x").replace(",", ".")
    s = re.sub(r"\s+", "", s)
    m = re.search(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", s)
    if m:
        return f"{m.group(1)}x{m.group(2)}"
    return s


def _normalize_qm(text: str) -> str:
    s = (text or "").strip().lower()
    if s == "kb":
        return "kesib buklash"
    return (text or "").strip()


def _parse_qty_and_unit(text: str) -> Tuple[Optional[int], str, str]:
    t = (text or "").strip().lower()
    if not t:
        return None, "", ""

    m = re.match(r"^\s*(\d[\d\s]*)\s*([a-zA-Zа-яА-ЯёЁ]*)\s*$", t)
    if not m:
        d = _digits_only(t)
        return (int(d) if d else None), "sht", "шт"

    qty = int(_digits_only(m.group(1) or "0") or "0")
    unit = (m.group(2) or "").strip().lower()

    if qty <= 0:
        return None, "", ""

    if unit in ("d", "dona"):
        return qty, "dona", "шт"
    if unit in ("sh", "sht", "шт"):
        return qty, "sht", "шт"

    return qty, "sht", "шт"


def _tg_now_as_ms_moment() -> str:
    dt_tg = datetime.now(TG_TZ)
    dt_ms = dt_tg.astimezone(MS_TZ)
    return dt_ms.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_ms_to_tg(moment_iso: str) -> str:
    if not moment_iso:
        return ""
    try:
        dt_ms = datetime.strptime(moment_iso[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=MS_TZ)
        return dt_ms.astimezone(TG_TZ).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return moment_iso


def _extract_sale_price_uzs(prod: Dict[str, Any]) -> int:
    sale_prices = prod.get("salePrices") or []
    if not sale_prices:
        return 0
    first = sale_prices[0] or {}
    value = first.get("value")
    if not isinstance(value, int):
        return 0
    return int(value // 100) if value >= 100 else int(value)


def _product_title(prod: Dict[str, Any]) -> str:
    return (prod.get("name") or "").strip() or "NoName"


def _cleanup(context: ContextTypes.DEFAULT_TYPE):
    for k in ("tk_products_map", "tk_product", "tk_form", "tk_edit_key", "tk_wait"):
        context.user_data.pop(k, None)


def _preview_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    d = context.user_data.get("tk_form") or {}
    qty_show = _fmt_num(d.get("qty"))
    if d.get("qty_unit_lat"):
        qty_show = f"{qty_show} {d.get('qty_unit_lat')}"

    moment_iso = (d.get("moment_iso_override") or "").strip() or _tg_now_as_ms_moment()
    moment_show = _fmt_ms_to_tg(moment_iso)

    return "\n".join([
        "🔎 Tekshiruv (Takror):",
        "",
        f"🏷 {(d.get('brand') or '-').upper()}",
        f"🧾 {d.get('item_type') or '-'}",
        f"📏 {d.get('size') or '-'}",
        f"📝 {d.get('qm_note') or '-'}",
        f"🔢 {qty_show}",
        f"💰 {_fmt_num(d.get('price_uzs'))}",
        f"📊 {d.get('channel_name') or 'Zakariyo 02'}",
        f"📁 {d.get('group_name') or 'karobka'}",
        f"🏬 {CONFIRM_STORE_NAME}",
        f"🕒 {moment_show}",
    ])


def _preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data="tkr:ok")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data="tkr:edit")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="tkr:cancel")],
    ])


def _edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏷 Brend", callback_data="tkr_edit:brand"),
         InlineKeyboardButton("🧾 Turi", callback_data="tkr_edit:item_type")],
        [InlineKeyboardButton("📏 Razmer", callback_data="tkr_edit:size"),
         InlineKeyboardButton("📝 Q.M", callback_data="tkr_edit:qm")],
        [InlineKeyboardButton("🔢 Soni", callback_data="tkr_edit:qty"),
         InlineKeyboardButton("💰 Narx", callback_data="tkr_edit:price")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="tkr:back")],
    ])


async def takror_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("operator"):
        await update.message.reply_text("❌ Avval /login qiling.", reply_markup=_menu_keyboard())
        return ConversationHandler.END

    _cleanup(context)
    context.user_data["tk_form"] = {
        "brand": "",
        "item_type": "",
        "size": "",
        "qm_note": "",
        "qty": None,
        "qty_unit_lat": "sht",
        "qty_unit_ru": "шт",
        "price_uzs": None,
        "channel_name": "Zakariyo 02",
        "group_name": "karobka",
    }

    await update.message.reply_text("🔁 Takror: tovar nomini yozing.\nMasalan: jakard, birka 4x4")
    return TK_SEARCH


async def takror_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()
    if not q:
        await update.message.reply_text("❌ Tovar nomini yozing.")
        return TK_SEARCH

    rows = search_products(q, limit=10) or []
    if not rows:
        await update.message.reply_text("❌ Tovar topilmadi. Boshqa nom yozing.")
        return TK_SEARCH

    mp: Dict[str, Dict[str, Any]] = {}
    kb: List[List[InlineKeyboardButton]] = []
    for r in rows[:10]:
        pid = str(r.get("id") or "")
        if not pid:
            continue
        mp[pid] = r
        kb.append([InlineKeyboardButton(_product_title(r)[:64], callback_data=f"tkp:{pid}")])

    context.user_data["tk_products_map"] = mp
    await update.message.reply_text("Tovardan birini tanlang:", reply_markup=InlineKeyboardMarkup(kb))
    return TK_PICK


async def takror_pick_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    pid = (q.data or "").split("tkp:", 1)[-1].strip()
    prod = (context.user_data.get("tk_products_map") or {}).get(pid) or get_product_by_id(pid)
    if not prod:
        await q.edit_message_text("❌ Tovar topilmadi. Qaytadan /takror qiling.")
        return ConversationHandler.END

    context.user_data["tk_product"] = prod
    d = context.user_data.get("tk_form") or {}
    d["item_type"] = _product_title(prod)
    d["price_uzs"] = _extract_sale_price_uzs(prod)
    context.user_data["tk_form"] = d
    context.user_data["tk_wait"] = "qm"

    await q.edit_message_text("📝 Q.M (izoh) kiriting. Masalan: kb")
    return TK_EXTRA


async def takror_extra_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data.get("tk_form") or {}
    stage = context.user_data.get("tk_wait") or "qm"
    txt = (update.message.text or "").strip()

    if stage == "qm":
        d["qm_note"] = _normalize_qm(txt)
        context.user_data["tk_form"] = d
        context.user_data["tk_wait"] = "qty"
        await update.message.reply_text("🔢 Sonini kiriting. Masalan: 3000 sh yoki 3000 d")
        return TK_QTY

    if stage == "price":
        nums = re.findall(r"(\d+)", txt)
        if not nums:
            await update.message.reply_text("❌ Narx noto'g'ri. Masalan: 450")
            return TK_EXTRA
        d["price_uzs"] = int(nums[-1])
        context.user_data["tk_form"] = d
        context.user_data.pop("tk_wait", None)
        await update.message.reply_text(_preview_text(context), reply_markup=_preview_kb())
        return TK_REVIEW

    await update.message.reply_text("❌ Noto'g'ri bosqich. /takror ni qaytadan bosing.")
    return ConversationHandler.END


async def takror_qty_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data.get("tk_form") or {}
    qty, unit_lat, unit_ru = _parse_qty_and_unit(update.message.text or "")
    if not qty:
        await update.message.reply_text("❌ Soni noto‘g‘ri. Masalan: 3000 sh yoki 3000 d")
        return TK_QTY

    d["qty"] = qty
    d["qty_unit_lat"] = unit_lat
    d["qty_unit_ru"] = unit_ru
    context.user_data["tk_form"] = d

    await update.message.reply_text("💰 Narxini kiriting. Masalan: 450")
    context.user_data["tk_wait"] = "price"
    return TK_EXTRA


async def takror_review_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if data == "tkr:cancel":
        _cleanup(context)
        await q.edit_message_text("❌ Bekor qilindi.")
        return ConversationHandler.END

    if data == "tkr:edit":
        await q.edit_message_text(_preview_text(context), reply_markup=_edit_kb())
        return TK_PICK

    if data == "tkr:back":
        await q.edit_message_text(_preview_text(context), reply_markup=_preview_kb())
        return TK_REVIEW

    if data != "tkr:ok":
        return TK_REVIEW

    prod = context.user_data.get("tk_product") or {}
    d = context.user_data.get("tk_form") or {}
    operator = context.user_data.get("operator") or {}

    product_meta = prod.get("meta")
    if not product_meta:
        await q.edit_message_text("❌ Product meta topilmadi.")
        return ConversationHandler.END

    try:
        org = get_default_organization()
        store_meta = find_store_meta_by_name(CONFIRM_STORE_NAME)
        if not store_meta:
            raise RuntimeError(f"Sklad topilmadi: {CONFIRM_STORE_NAME}")

        qty = int(d.get("qty") or 0)
        price_uzs = int(d.get("price_uzs") or 0)

        cp_meta = {"href": "", "type": "counterparty", "mediaType": "application/json"}

        positions = [{
            "assortment": {"meta": product_meta},
            "quantity": float(qty),
            "price": int(price_uzs) * 100 if price_uzs > 0 else 0,
        }]

        moment_iso = _tg_now_as_ms_moment()

        desc = "\n".join([
            f"[BOT TAKROR] Operator: {operator.get('name')}",
            f"Product: {d.get('item_type')}",
            f"Size: {d.get('size') or '-'}",
            f"Qty: {qty}",
            f"QM: {d.get('qm_note') or '-'}",
        ])

        order = create_customerorder(
            organization_meta=org["meta"],
            agent_meta=cp_meta,
            sales_channel_meta=None,
            store_meta=store_meta,
            moment_iso=moment_iso,
            description=desc,
            positions=positions,
        )

        if CONFIRM_CHAT_ID:
            await context.bot.send_message(chat_id=CONFIRM_CHAT_ID, text=_preview_text(context) + f"\n🧾 {order.get('name', 'N/A')}")

        await q.edit_message_text("✅ Takror buyurtma yuborildi.")
        _cleanup(context)
        return ConversationHandler.END

    except Exception as e:
        await q.edit_message_text(f"❌ Takror yuborishda xatolik: {e}")
        return ConversationHandler.END


async def takror_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if not data.startswith("tkr_edit:"):
        return TK_REVIEW

    key = data.split(":", 1)[1]
    context.user_data["tk_edit_key"] = key

    prompts = {
        "brand": "🏷 Brend:",
        "item_type": "🧾 Maxsulot turi:",
        "size": "📏 Razmer (masalan: 1.5x5):",
        "qm": "📝 Q.M (masalan: kb):",
        "qty": "🔢 Soni (masalan: 3000 sh yoki 3000 d):",
        "price": "💰 Narx (masalan: 450):",
    }
    await q.edit_message_text(prompts.get(key, "Qiymat kiriting:"))
    return TK_EDIT_VALUE


async def takror_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = context.user_data.get("tk_edit_key")
    d = context.user_data.get("tk_form") or {}
    val = (update.message.text or "").strip()

    if key == "brand":
        d["brand"] = val.upper()
    elif key == "item_type":
        d["item_type"] = val
    elif key == "size":
        d["size"] = _normalize_size(val)
    elif key == "qm":
        d["qm_note"] = _normalize_qm(val)
    elif key == "qty":
        qty, unit_lat, unit_ru = _parse_qty_and_unit(val)
        if not qty:
            await update.message.reply_text("❌ Soni noto‘g‘ri. Masalan: 3000 sh yoki 3000 d")
            return TK_EDIT_VALUE
        d["qty"] = qty
        d["qty_unit_lat"] = unit_lat
        d["qty_unit_ru"] = unit_ru
    elif key == "price":
        nums = re.findall(r"(\d+)", val)
        if not nums:
            await update.message.reply_text("❌ Narx noto‘g‘ri. Masalan: 450")
            return TK_EDIT_VALUE
        d["price_uzs"] = int(nums[-1])

    context.user_data["tk_form"] = d
    context.user_data.pop("tk_edit_key", None)

    await update.message.reply_text(_preview_text(context), reply_markup=_preview_kb())
    return TK_REVIEW


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup(context)
    await update.message.reply_text("Bekor qilindi.", reply_markup=_menu_keyboard())
    return ConversationHandler.END
