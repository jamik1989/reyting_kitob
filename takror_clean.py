from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re
import logging
from difflib import SequenceMatcher
import tempfile
from pathlib import Path
import requests

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
from ..services import moysklad as _ms_mod

TK_SEARCH, TK_PICK, TK_EXTRA, TK_QTY, TK_REVIEW, TK_EDIT_VALUE = range(6)
logger = logging.getLogger(__name__)

TG_TZ = ZoneInfo(os.getenv("TG_TZ", "Asia/Tashkent"))
MS_TZ = ZoneInfo(os.getenv("MOYSKLAD_TZ", "Europe/Moscow"))

CONFIRM_STORE_NAME = "Abusahiy 75"

try:
    from app.handlers import confirm as _confirm_mod
except Exception:
    _confirm_mod = None


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


def _extract_size_from_product(prod: Dict[str, Any]) -> str:
    name = _product_title(prod)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*[xXхХ*]\s*(\d+(?:[.,]\d+)?)", name or "")
    if m:
        return _normalize_size(f"{m.group(1)}x{m.group(2)}")

    m2 = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:sm|cm|см)\D+(\d+(?:[.,]\d+)?)\s*(?:sm|cm|см)", name or "", re.IGNORECASE)
    if m2:
        return _normalize_size(f"{m2.group(1)}x{m2.group(2)}")

    m3 = re.search(r"(\d+(?:[.,]\d+)?)\s*(sm|cm|см)\b", name or "", re.IGNORECASE)
    if m3:
        num = (m3.group(1) or "").replace(",", ".").strip()
        unit = (m3.group(2) or "sm").lower()
        if unit == "cm":
            unit = "sm"
        if unit == "см":
            unit = "sm"
        return f"{num}{unit}"

    attrs = prod.get("attributes") or []
    if isinstance(attrs, list):
        for a in attrs:
            if not isinstance(a, dict):
                continue
            n = str(a.get("name") or "").lower()
            if "razmer" in n or "size" in n:
                val = a.get("value")
                if isinstance(val, str) and val.strip():
                    return _normalize_size(val)
    return ""


def _cleanup(context: ContextTypes.DEFAULT_TYPE):
    for k in (
        "tk_products_map",
        "tk_product",
        "tk_form",
        "tk_edit_key",
        "tk_wait",
        "tk_phase",
        "tk_cp_meta",
        "tk_cp_name",
        "tk_cp_candidates",
        "tk_edit_products_map",
    ):
        context.user_data.pop(k, None)


def _find_callable(name: str):
    fn = globals().get(name)
    if callable(fn):
        return fn
    if _confirm_mod is not None:
        fn = getattr(_confirm_mod, name, None)
        if callable(fn):
            return fn
    return None


def _search_counterparties(query: str):
    names = [
        "search_counterparties",
        "search_counterparty",
        "find_counterparties",
        "find_counterparty",
        "search_counterparties_by_query",
        "find_counterparties_for_query",
    ]
    for name in names:
        fn = _find_callable(name)
        if not fn:
            continue
        try:
            rows = fn(query, limit=8)
        except TypeError:
            rows = fn(query)
        except Exception:
            rows = []
        if rows:
            return rows
    return []


def _rank_counterparties(rows: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return rows

    def score(r: Dict[str, Any]) -> float:
        name = str(r.get("name") or "").strip().lower()
        phone = str(r.get("phone") or "").strip().lower()
        if name.startswith(q):
            return 100.0
        if q in name:
            return 90.0
        if q in phone:
            return 80.0
        return SequenceMatcher(None, q, name).ratio() * 70.0

    return sorted(rows, key=score, reverse=True)


def _create_counterparty(name: str, phone: str):
    names = [
        "create_counterparty",
        "create_counterparty_if_not_exists",
        "create_counterparty_minimal",
        "create_counterparty_simple",
    ]
    for helper_name in names:
        fn = _find_callable(helper_name)
        if not fn:
            continue
        try:
            return fn(name=name, phone=phone)
        except TypeError:
            try:
                return fn(name, phone)
            except Exception:
                pass
        except Exception:
            pass
    return None


def _extract_cp_meta(cp_obj: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(cp_obj, dict):
        return None
    meta = cp_obj.get("meta")
    if isinstance(meta, dict):
        return meta
    if cp_obj.get("id"):
        return {
            "href": f"https://api.moysklad.ru/api/remap/1.2/entity/counterparty/{cp_obj['id']}",
            "type": "counterparty",
            "mediaType": "application/json",
        }
    return None


def _best_cp(rows: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    q = (query or "").strip().lower()
    for r in rows:
        name = str(r.get("name") or "").strip().lower()
        phone = str(r.get("phone") or "").strip().lower()
        if q and (q == name or q in name or q in phone):
            return r
    return rows[0]


def _get_repeat_product_image(prod: Dict[str, Any], context: Optional[ContextTypes.DEFAULT_TYPE] = None) -> str:
    if not isinstance(prod, dict):
        return ""
    for k in ("image_path", "photo_path", "imageUrl", "image_url"):
        v = (prod.get(k) or "").strip() if isinstance(prod.get(k), str) else ""
        if v:
            if "api.moysklad.ru" in v:
                local = _download_ms_image_to_tmp(v)
                if local:
                    return local
                # Protected MoySklad URL cannot be sent to Telegram directly without auth.
                continue
            return v

    image = prod.get("image") or {}
    if isinstance(image, dict):
        for k in ("href", "downloadHref", "url"):
            v = image.get(k)
            if isinstance(v, str) and v.strip():
                vv = v.strip()
                if "api.moysklad.ru" in vv:
                    local = _download_ms_image_to_tmp(vv)
                    if local:
                        return local
                    continue
                return vv

    images = prod.get("images") or {}
    rows = images.get("rows") if isinstance(images, dict) else None
    if isinstance(rows, list) and rows:
        first = rows[0] or {}
        meta = first.get("meta") if isinstance(first, dict) else None
        if isinstance(meta, dict):
            href = (meta.get("downloadHref") or meta.get("href") or "").strip()
            if href:
                if "api.moysklad.ru" in href:
                    local = _download_ms_image_to_tmp(href)
                    if local:
                        return local
                    # Protected URL without successful download: try other strategies below.
                    href = ""
                if href:
                    return href

    for helper in (
        "_get_repeat_product_image",
        "_get_product_image_path",
        "_download_product_image",
        "_download_image_to_tmp",
    ):
        fn = _find_callable(helper)
        if not fn:
            continue
        try:
            v = fn(prod, context)
            return (v or "").strip() if isinstance(v, str) else ""
        except TypeError:
            try:
                v = fn(prod)
                return (v or "").strip() if isinstance(v, str) else ""
            except TypeError:
                try:
                    v = fn(prod.get("id") if isinstance(prod, dict) else prod)
                    return (v or "").strip() if isinstance(v, str) else ""
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    api_image = _fetch_product_image_from_ms(prod)
    if api_image:
        return api_image
    return ""


def _download_ms_image_to_tmp(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    token = os.getenv("MOYSKLAD_TOKEN", "").strip() or str(getattr(_ms_mod, "MOYSKLAD_TOKEN", "") or "").strip()
    ms_login = os.getenv("MOYSKLAD_LOGIN", "").strip() or os.getenv("MOYSKLAD_USER", "").strip()
    ms_pass = os.getenv("MOYSKLAD_PASSWORD", "").strip() or os.getenv("MOYSKLAD_PASS", "").strip()

    headers = {
        "Accept": "application/octet-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    candidates = [url]
    if "/download" not in url:
        candidates.append(url.rstrip("/") + "/download")

    for candidate in candidates:
        try:
            r = requests.get(candidate, headers=headers, auth=((ms_login, ms_pass) if not token and ms_login and ms_pass else None), timeout=20)
            if r.status_code != 200:
                continue
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "image" not in ctype and "octet-stream" not in ctype:
                continue
            suffix = ".jpg"
            if "png" in ctype:
                suffix = ".png"
            tmp_path = Path(tempfile.gettempdir()) / f"tk_ms_{os.getpid()}_{abs(hash(candidate))}{suffix}"
            tmp_path.write_bytes(r.content)
            return str(tmp_path)
        except Exception:
            continue
    return ""


def _fetch_product_image_from_ms(prod: Dict[str, Any]) -> str:
    if not isinstance(prod, dict):
        return ""
    token = os.getenv("MOYSKLAD_TOKEN", "").strip() or str(getattr(_ms_mod, "MOYSKLAD_TOKEN", "") or "").strip()
    ms_login = os.getenv("MOYSKLAD_LOGIN", "").strip() or os.getenv("MOYSKLAD_USER", "").strip()
    ms_pass = os.getenv("MOYSKLAD_PASSWORD", "").strip() or os.getenv("MOYSKLAD_PASS", "").strip()

    pid = str(prod.get("id") or "").strip()
    meta = prod.get("meta") if isinstance(prod.get("meta"), dict) else {}
    meta_href = (meta.get("href") or "").strip() if isinstance(meta, dict) else ""

    candidates = []
    if pid:
        candidates.append(f"https://api.moysklad.ru/api/remap/1.2/entity/product/{pid}/images")
    if meta_href:
        candidates.append(meta_href.rstrip("/") + "/images")

    for url in candidates:
        try:
            data = _ms_get_json(url)
            if not data:
                headers = {"Accept": "application/json"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                r = requests.get(url, headers=headers, auth=((ms_login, ms_pass) if not token and ms_login and ms_pass else None), timeout=20)
                if r.status_code != 200:
                    continue
                data = r.json() if r.content else {}
            rows = data.get("rows") if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                continue
            first = rows[0] or {}
            first_meta = first.get("meta") if isinstance(first, dict) else None
            if not isinstance(first_meta, dict):
                continue
            href = (first_meta.get("downloadHref") or first_meta.get("href") or "").strip()
            if not href:
                continue
            local = _download_ms_image_to_tmp(href)
            if local:
                return local
        except Exception:
            continue
    return ""


def _fetch_product_full_from_ms(pid: str) -> Dict[str, Any]:
    pid = (pid or "").strip()
    if not pid:
        return {}
    token = os.getenv("MOYSKLAD_TOKEN", "").strip() or str(getattr(_ms_mod, "MOYSKLAD_TOKEN", "") or "").strip()
    ms_login = os.getenv("MOYSKLAD_LOGIN", "").strip() or os.getenv("MOYSKLAD_USER", "").strip()
    ms_pass = os.getenv("MOYSKLAD_PASSWORD", "").strip() or os.getenv("MOYSKLAD_PASS", "").strip()
    url = f"https://api.moysklad.ru/api/remap/1.2/entity/product/{pid}?expand=images"
    try:
        data = _ms_get_json(url)
        if not data:
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            r = requests.get(url, headers=headers, auth=((ms_login, ms_pass) if not token and ms_login and ms_pass else None), timeout=20)
            if r.status_code != 200:
                return {}
            data = r.json() if r.content else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _ms_get_json(url: str) -> Dict[str, Any]:
    if not url:
        return {}
    # Try to reuse already-authenticated moysklad service helpers first.
    for fn_name in ("ms_get", "api_get", "_api_get", "_get", "_request_json", "_request"):
        fn = getattr(_ms_mod, fn_name, None)
        if not callable(fn):
            continue
        try:
            if fn_name == "_request":
                data = fn("GET", url)
            elif fn_name == "ms_get":
                path = url.split("/api/remap/1.2/", 1)[-1]
                if not path.startswith("/"):
                    path = "/" + path
                data = fn(path)
            else:
                data = fn(url)
            if isinstance(data, dict):
                return data
        except TypeError:
            try:
                # some helpers expect path only
                path = url.split("/api/remap/1.2/", 1)[-1]
                data = fn(path)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        except Exception:
            pass
    return {}


async def _send_preview_with_optional_image(target_message, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data.get("tk_form") or {}
    text = _preview_text(context)
    kb = _preview_kb()

    img = (d.get("image_path") or "").strip()
    if not img:
        prod = context.user_data.get("tk_product") or {}
        img = _get_repeat_product_image(prod, context)
        if img:
            d["image_path"] = img
            context.user_data["tk_form"] = d

    if img:
        try:
            if img.startswith("http://") or img.startswith("https://"):
                await context.bot.send_photo(
                    chat_id=target_message.chat_id,
                    photo=img,
                    caption=text,
                    reply_markup=kb,
                )
                return TK_PICK
            if os.path.exists(img):
                with open(img, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=target_message.chat_id,
                        photo=f,
                        caption=text,
                        reply_markup=kb,
                    )
                    return TK_PICK
        except Exception as e_photo:
            logger.warning(
                "takror preview send_photo failed: chat_id=%s img=%s exists=%s err=%r",
                getattr(target_message, "chat_id", None),
                img[:300] if isinstance(img, str) else type(img).__name__,
                os.path.exists(img) if isinstance(img, str) else False,
                e_photo,
            )
            # fallback: some clients/channels reject photo but accept document
            try:
                if os.path.exists(img):
                    with open(img, "rb") as f:
                        await context.bot.send_document(
                            chat_id=target_message.chat_id,
                            document=f,
                            caption=text,
                            reply_markup=kb,
                        )
                        return TK_PICK
            except Exception as e_doc:
                logger.warning(
                    "takror preview send_document failed: chat_id=%s img=%s exists=%s err=%r",
                    getattr(target_message, "chat_id", None),
                    img[:300] if isinstance(img, str) else type(img).__name__,
                    os.path.exists(img) if isinstance(img, str) else False,
                    e_doc,
                )
            await context.bot.send_message(chat_id=target_message.chat_id, text="⚠️ Rasmni yuborib bo‘lmadi, matnli preview yuborildi.")

    await target_message.reply_text(text, reply_markup=kb)
    return TK_PICK


def _preview_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    d = context.user_data.get("tk_form") or {}
    qty_show = _fmt_num(d.get("qty"))
    qty_unit = (d.get("qty_unit_lat") or "").strip().lower()
    if qty_unit in ("sht", "sh", "шт", ""):
        qty_unit = "dona"
    if qty_unit:
        qty_show = f"{qty_show} {qty_unit}"

    moment_iso = (d.get("moment_iso_override") or "").strip() or _tg_now_as_ms_moment()
    moment_show = _fmt_ms_to_tg(moment_iso)

    return "\n".join([
        "#takror",
        "",
        f"🏷 {(d.get('brand') or '-').upper()}",
        f"🧾 {d.get('item_type') or '-'}",
        f"📏 {d.get('size') or '-'}",
        f"📝 {d.get('qm_note') or '-'}",
        f"🔢 {qty_show}",
        f"💰 {_fmt_num(d.get('price_uzs'))}",
        f"📊 {d.get('channel_name') or 'Zakariyo 02'}",
        f"📁 {d.get('group_name') or 'karobka'}",
        "",
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
        [InlineKeyboardButton("📝 Q.M", callback_data="tkr_edit:qm")],
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
    context.user_data["tk_phase"] = "cp"
    await update.message.reply_text(
        "🏷 Brend yoki mijoz yoki telefon yozing.\n"
        "Agar topilmasa: BRAND-Mijoz-901234567 formatida yuboring."
    )
    return TK_SEARCH


async def takror_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()
    phase = context.user_data.get("tk_phase") or "cp"
    d = context.user_data.get("tk_form") or {}

    if not q:
        if phase == "cp":
            await update.message.reply_text("❌ Brend/mijoz/telefon kiriting.")
        else:
            await update.message.reply_text("❌ Tovar nomini yozing.")
        return TK_SEARCH

    if phase in ("cp", "edit_brand"):
        rows = _rank_counterparties(_search_counterparties(q), q)
        if rows:
            context.user_data["tk_cp_candidates"] = rows[:20]
            kb_rows = []
            for i, item in enumerate(rows[:12]):
                nm = str(item.get("name") or "-").strip()
                ph = str(item.get("phone") or "").strip()
                label = f"{nm}" + (f" ({ph})" if ph else "")
                kb_rows.append([InlineKeyboardButton(f"✅ {label[:58]}", callback_data=f"tkr_cp:{i}")])

            title = "Natijalar:\n— Agar ✅ OPEN tasdiq chiqsa, o‘shani tanlang.\n— Aks holda kontragentni tanlang."
            if phase == "edit_brand":
                title = "Brend uchun natijalar:\n— Keraklisini tanlang."
            await update.message.reply_text(title, reply_markup=InlineKeyboardMarkup(kb_rows))
            return TK_PICK

        m = re.match(r"^\s*([^-]+)-([^-]+)-(\+?\d{7,15})\s*$", q)
        if m:
            brand = (m.group(1) or "").strip().upper()
            client_name = (m.group(2) or "").strip()
            phone = (m.group(3) or "").strip()
            cp_obj = _create_counterparty(client_name, phone)
            d["brand"] = brand
            context.user_data["tk_form"] = d
            context.user_data["tk_cp_meta"] = _extract_cp_meta(cp_obj or {})
            context.user_data["tk_cp_name"] = client_name
            context.user_data["tk_phase"] = "product"
            if phase == "edit_brand":
                await update.message.reply_text(
                    f"✅ Brend yangilandi: {brand} / {client_name} ({phone})\n\n{_preview_text(context)}",
                    reply_markup=_edit_kb(),
                )
                return TK_PICK
            await update.message.reply_text(
                f"✅ Yangi kontragent qabul qilindi: {brand} / {client_name} ({phone})\n\n"
                "🔁 Takror: tovar nomini yozing."
            )
            return TK_SEARCH

        await update.message.reply_text(
            "❌ Kontragent topilmadi.\n"
            "Qayta yozing yoki yaratish uchun: BRAND-Mijoz-901234567"
        )
        return TK_SEARCH

    if phase == "edit_item":
        rows = search_products(q, limit=10) or []
        if not rows:
            await update.message.reply_text("❌ Tovar topilmadi. Boshqa nom yozing.")
            return TK_SEARCH
        mp: Dict[str, Dict[str, Any]] = {}
        kb: List[List[InlineKeyboardButton]] = []
        for r in rows[:10]:
            pid = str(r.get("id") or "").strip()
            if not pid:
                continue
            mp[pid] = r
            kb.append([InlineKeyboardButton(_product_title(r)[:64], callback_data=f"tkr_item:{pid}")])
        context.user_data["tk_edit_products_map"] = mp
        await update.message.reply_text("🧾 Yangi tovarni tanlang:", reply_markup=InlineKeyboardMarkup(kb))
        return TK_PICK

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
    mapped = (context.user_data.get("tk_products_map") or {}).get(pid)
    prod_full = get_product_by_id(pid)
    prod_api = _fetch_product_full_from_ms(pid)
    prod = prod_api or prod_full or mapped
    if not prod:
        await q.edit_message_text("❌ Tovar topilmadi. Qaytadan /takror qiling.")
        return ConversationHandler.END

    context.user_data["tk_product"] = prod
    d = context.user_data.get("tk_form") or {}
    d["item_type"] = _product_title(prod)
    d["price_uzs"] = _extract_sale_price_uzs(prod)
    auto_size = _extract_size_from_product(prod)
    if auto_size:
        d["size"] = auto_size
    context.user_data["tk_form"] = d
    context.user_data["tk_wait"] = "qm"
    context.user_data["tk_phase"] = "product"

    img = _get_repeat_product_image(prod, context)
    if img:
        d["image_path"] = img
        context.user_data["tk_form"] = d
        try:
            if img.startswith("http://") or img.startswith("https://"):
                await context.bot.send_photo(chat_id=q.message.chat_id, photo=img, caption="🖼 Topilgan tovar rasmi")
            elif os.path.exists(img):
                with open(img, "rb") as f:
                    await context.bot.send_photo(chat_id=q.message.chat_id, photo=f, caption="🖼 Topilgan tovar rasmi")
        except Exception as e_photo:
            logger.warning(
                "takror product send_photo failed: chat_id=%s img=%s exists=%s err=%r",
                getattr(q.message, "chat_id", None),
                img[:300] if isinstance(img, str) else type(img).__name__,
                os.path.exists(img) if isinstance(img, str) else False,
                e_photo,
            )
            try:
                if os.path.exists(img):
                    with open(img, "rb") as f:
                        await context.bot.send_document(chat_id=q.message.chat_id, document=f, caption="🖼 Topilgan tovar rasmi")
                else:
                    await context.bot.send_document(chat_id=q.message.chat_id, document=img, caption="🖼 Topilgan tovar rasmi")
            except Exception as e_doc:
                logger.warning(
                    "takror product send_document failed: chat_id=%s img=%s exists=%s err=%r",
                    getattr(q.message, "chat_id", None),
                    img[:300] if isinstance(img, str) else type(img).__name__,
                    os.path.exists(img) if isinstance(img, str) else False,
                    e_doc,
                )
                await context.bot.send_message(chat_id=q.message.chat_id, text="⚠️ Tovar rasmi topildi, lekin yuborishda xatolik bo‘ldi.")
    else:
        await context.bot.send_message(chat_id=q.message.chat_id, text="ℹ️ Bu tovarni rasmi yo‘q.")

    await q.edit_message_text("📝 Q.M (izoh) kiriting. Masalan: kb")
    return TK_EXTRA


async def takror_cp_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    data = q.data or ""
    if not data.startswith("tkr_cp:"):
        return TK_PICK

    try:
        idx = int(data.split(":", 1)[1])
    except Exception:
        await q.edit_message_text("❌ Kontragent tanlashda xatolik.")
        return TK_SEARCH

    rows = context.user_data.get("tk_cp_candidates") or []
    if idx < 0 or idx >= len(rows):
        await q.edit_message_text("❌ Kontragent topilmadi, qaytadan yozing.")
        return TK_SEARCH

    cp = rows[idx] or {}
    cp_name = (cp.get("name") or "-").strip()
    d = context.user_data.get("tk_form") or {}
    mode_before = context.user_data.get("tk_phase")
    d["brand"] = cp_name.upper()
    context.user_data["tk_form"] = d
    context.user_data["tk_cp_meta"] = _extract_cp_meta(cp)
    context.user_data["tk_cp_name"] = cp_name
    context.user_data["tk_phase"] = "product"

    if mode_before == "edit_brand":
        context.user_data["tk_phase"] = "product"
        await q.edit_message_text(
            f"✅ Brend yangilandi: {cp_name}\n\n{_preview_text(context)}",
            reply_markup=_edit_kb(),
        )
        return TK_PICK

    await q.edit_message_text(f"✅ Tanlandi: {cp_name}\n\n🔁 Takror: tovar nomini yozing.")
    return TK_SEARCH


async def takror_edit_product_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    data = q.data or ""
    if not data.startswith("tkr_item:"):
        return TK_PICK

    pid = data.split(":", 1)[1].strip()
    prod = (context.user_data.get("tk_edit_products_map") or {}).get(pid) or get_product_by_id(pid) or _fetch_product_full_from_ms(pid)
    if not prod:
        await q.edit_message_text("❌ Tovar topilmadi.")
        return TK_PICK

    d = context.user_data.get("tk_form") or {}
    d["item_type"] = _product_title(prod)
    d["price_uzs"] = _extract_sale_price_uzs(prod)
    auto_size = _extract_size_from_product(prod)
    if auto_size:
        d["size"] = auto_size
    img = _get_repeat_product_image(prod, context)
    if img:
        d["image_path"] = img
    context.user_data["tk_form"] = d
    context.user_data["tk_product"] = prod
    context.user_data["tk_phase"] = "product"

    await q.edit_message_text(
        f"✅ Turi yangilandi: {d.get('item_type')}\n\n{_preview_text(context)}",
        reply_markup=_edit_kb(),
    )
    return TK_PICK


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
        return await _send_preview_with_optional_image(update.message, context)

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
    try:
        await q.answer()
    except Exception:
        pass

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
        return TK_PICK

    if data != "tkr:ok":
        return TK_PICK

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

        cp_meta = context.user_data.get("tk_cp_meta") or {"href": "", "type": "counterparty", "mediaType": "application/json"}

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
    try:
        await q.answer()
    except Exception:
        pass

    data = q.data or ""
    if not data.startswith("tkr_edit:"):
        return TK_PICK

    key = data.split(":", 1)[1]
    context.user_data["tk_edit_key"] = key

    if key == "brand":
        context.user_data["tk_phase"] = "edit_brand"
        await q.edit_message_text("🏷 Yangi brend/mijoz/telefon kiriting (qidiruv ochiladi):")
        return TK_SEARCH
    if key == "item_type":
        context.user_data["tk_phase"] = "edit_item"
        await q.edit_message_text("🧾 Yangi tovar nomini kiriting (qidiruv ochiladi):")
        return TK_SEARCH

    prompts = {
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
    return TK_PICK


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _cleanup(context)
    await update.message.reply_text("Bekor qilindi.", reply_markup=_menu_keyboard())
    return ConversationHandler.END
