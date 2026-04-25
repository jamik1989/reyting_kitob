$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\Jamshed_Artikov\zakbotbirka\app\zakariyoakabotlari"
Set-Location $projectRoot

$path = ".\app\handlers\takror.py"
if (!(Test-Path $path)) {
    Write-Host "Fayl topilmadi: $path" -ForegroundColor Red
    exit 1
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = ".\app\handlers\takror.py.before_text_image_edit_fix_$stamp"
Copy-Item $path $backup -Force
Write-Host "Backup yaratildi: $backup" -ForegroundColor Green

$content = Get-Content $path -Raw -Encoding UTF8

# Mojibake / buzilgan yozuvlarni tozalash
$replacements = @{
    'рџ“ќ Q\.M \(izoh\) kiriting\. Masalan: kb' = '📝 Q.M (izoh) kiriting. Masalan: kb'
    'рџŽЁ Rangini kiriting\. Kerak bo''lmasa - deb yozing' = '🎨 Rangini kiriting. Kerak bo''lmasa - deb yozing'
    'рџ”ў Sonini kiriting\. Masalan: 3000 sh yoki 3000 d' = '🔢 Sonini kiriting. Masalan: 3000 sh yoki 3000 d'
    'рџ’° Narxini kiriting\. Masalan: 450' = '💰 Narxini kiriting. Masalan: 450'
    'рџ–ј Topilgan tovar rasmi' = '🖼 Topilgan tovar rasmi'
    'рџЏ· Brend yoki mijoz yoki telefon yozing\.' = '🏷 Brend yoki mijoz yoki telefon yozing.'
    'рџ”Ѓ Takror: tovar nomini yozing\.' = '🔁 Takror: tovar nomini yozing.'
    'рџ§ѕ' = '🧾'
    'рџ“Џ' = '📏'
    'рџ“ќ' = '📝'
    'рџŽЁ' = '🎨'
    'рџ”ў' = '🔢'
    'рџ’°' = '💰'
    'рџ“Љ' = '📊'
    'рџ“Ѓ' = '📁'
    'рџЏ¬' = '🏬'
    'рџ•’' = '🕒'
    'вњ…' = '✅'
    'вњЏ' = '✏️'
    'вќЊ' = '❌'
    'вћ•' = '➡️'
    'в¬…️' = '⬅️'
}

foreach ($k in $replacements.Keys) {
    $content = [regex]::Replace($content, $k, $replacements[$k])
}

# Oldingi fix blok bo'lsa olib tashlash
$content = [regex]::Replace(
    $content,
    '(?s)# ===== TAKROR_TEXT_IMAGE_EDIT_FIX =====.*?# ===== /TAKROR_TEXT_IMAGE_EDIT_FIX =====',
    ''
)

$append = @'

# ===== TAKROR_TEXT_IMAGE_EDIT_FIX =====

def _tk_safe_text(v, default="-"):
    try:
        s = str(v or "").strip()
        return s if s else default
    except Exception:
        return default

def _tk_preview_text_fixed(context: ContextTypes.DEFAULT_TYPE) -> str:
    d = context.user_data.get("tk_form") or {}
    qty_show = _fmt_num(d.get("qty"))
    if d.get("qty_unit_lat"):
        qty_show = f"{qty_show} {d.get('qty_unit_lat')}"
    moment_iso = (d.get("moment_iso_override") or "").strip() or _tg_now_as_ms_moment()
    moment_show = _fmt_ms_to_tg(moment_iso) or moment_iso

    lines = [
        "#takror",
        f"🏷 {_tk_safe_text(d.get('brand')).upper()}",
        f"🧾 {_tk_safe_text(d.get('item_type'))}",
        f"📏 {_tk_safe_text(d.get('size'))}",
        f"📝 {_tk_safe_text(d.get('qm_note'))}",
    ]

    bg = _tk_safe_text(d.get("bg_color"), "")
    if bg:
        lines.append(f"🎨 {bg}")

    lines.extend([
        f"🔢 {qty_show or '-'}",
        f"💰 {_fmt_num(d.get('price_uzs'))}",
        f"📊 {_tk_safe_text(d.get('channel_name'), 'Zakariyo 02')}",
        f"📁 {_tk_safe_text(d.get('group_name'), 'karobka')}",
        f"🏬 Abusahiy 75",
        f"🕒 {moment_show}",
    ])
    return "\n".join(lines)


async def _tk_send_preview_fixed(target_message, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data.get("tk_form") or {}
    text = _tk_preview_text_fixed(context)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data="tkr:ok")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data="tkr:edit")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="tkr:cancel")],
    ])

    img = (d.get("image_path") or "").strip()
    if img and os.path.exists(img):
        try:
            with open(img, "rb") as f:
                await context.bot.send_photo(
                    chat_id=target_message.chat_id,
                    photo=f,
                    caption=text,
                    reply_markup=kb,
                )
                return TK_REVIEW
        except Exception as e:
            logger.warning("TAKROR fixed preview photo send skipped: %s", e)

    await target_message.reply_text(text, reply_markup=kb)
    return TK_REVIEW


# original edit action ni saqlab qolish
try:
    takror_edit_action_orig
except NameError:
    try:
        takror_edit_action_orig = takror_edit_action
    except Exception:
        takror_edit_action_orig = None


async def takror_pick_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    # oldingi original product pickni ishlatamiz
    result = await takror_pick_product_orig(update, context)

    d = context.user_data.get("tk_form") or {}

    # image_path yo'q bo'lsa topishga qayta urinamiz
    try:
        prod = context.user_data.get("tk_product")
        if prod and not (d.get("image_path") or "").strip():
            img = _get_repeat_product_image(prod) or ""
            if img:
                d["image_path"] = img
                context.user_data["tk_form"] = d
                if os.path.exists(img):
                    with open(img, "rb") as f:
                        await context.bot.send_photo(
                            chat_id=q.message.chat_id,
                            photo=f,
                            caption="🖼 Topilgan tovar rasmi",
                        )
    except Exception as e:
        logger.warning("TAKROR image fix skipped: %s", e)

    context.user_data["tk_wait"] = "qm"
    await context.bot.send_message(chat_id=q.message.chat_id, text="📝 Q.M (izoh) kiriting. Masalan: kb")
    return TK_EXTRA


async def takror_extra_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data.get("tk_form") or {}
    stage = context.user_data.get("tk_wait") or "qm"
    txt = (update.message.text or "").strip()

    if stage == "qm":
        d["qm_note"] = _normalize_qm(txt)
        context.user_data["tk_form"] = d
        context.user_data["tk_wait"] = "bg"
        await update.message.reply_text("🎨 Rangini kiriting. Kerak bo'lmasa - deb yozing")
        return TK_EXTRA

    if stage == "bg":
        d["bg_color"] = "" if txt == "-" else txt
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
        return await _tk_send_preview_fixed(update.message, context)

    # eski logikaga fallback
    if 'takror_extra_text_orig' in globals() and callable(takror_extra_text_orig):
        return await takror_extra_text_orig(update, context)

    d["qm_note"] = _normalize_qm(txt)
    context.user_data["tk_form"] = d
    context.user_data["tk_wait"] = "bg"
    await update.message.reply_text("🎨 Rangini kiriting. Kerak bo'lmasa - deb yozing")
    return TK_EXTRA


async def takror_qty_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = context.user_data.get("tk_form") or {}
    txt = (update.message.text or "").strip()

    qty, unit_lat, unit_ru = _parse_qty_and_unit(txt)
    if not qty:
        await update.message.reply_text("❌ Soni noto'g'ri. Masalan: 3000 sh yoki 3000 d")
        return TK_QTY

    d["qty"] = qty
    d["qty_unit_lat"] = unit_lat
    d["qty_unit_ru"] = unit_ru
    context.user_data["tk_form"] = d
    context.user_data["tk_wait"] = "price"
    await update.message.reply_text("💰 Narxini kiriting. Masalan: 450")
    return TK_EXTRA


async def takror_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data if q else ""

    if data == "tkr:edit":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Q.M", callback_data="tkr_edit:qm"),
             InlineKeyboardButton("🎨 Rang", callback_data="tkr_edit:bg")],
            [InlineKeyboardButton("🔢 Soni", callback_data="tkr_edit:qty"),
             InlineKeyboardButton("💰 Narx", callback_data="tkr_edit:price")],
            [InlineKeyboardButton("🕒 Sana/Vaqt", callback_data="tkr_edit:time"),
             InlineKeyboardButton("📊 KL (Kanal)", callback_data="tkr_edit:channel")],
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="tkr:back")],
        ])
        preview = _tk_preview_text_fixed(context)
        try:
            await q.message.reply_text(preview, reply_markup=kb)
        except Exception:
            await context.bot.send_message(chat_id=q.message.chat_id, text=preview, reply_markup=kb)
        return TK_REVIEW

    if takror_edit_action_orig:
        return await takror_edit_action_orig(update, context)

    return TK_REVIEW

# ===== /TAKROR_TEXT_IMAGE_EDIT_FIX =====
'@

$content = $content.TrimEnd() + "`r`n`r`n" + $append + "`r`n"
Set-Content $path $content -Encoding UTF8

Write-Host "Takror text/image/edit fix yozildi." -ForegroundColor Green
Write-Host "Keyin ishga tushiring:" -ForegroundColor Yellow
Write-Host 'python -m app.main'
