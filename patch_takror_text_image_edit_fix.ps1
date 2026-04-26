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

# 1) accidental duplicate module blockni tozalash
$dupMarker = "# app/handlers/takror.py"
$first = $content.IndexOf($dupMarker)
if ($first -ge 0) {
    $second = $content.IndexOf($dupMarker, $first + $dupMarker.Length)
    if ($second -gt 0) {
        $content = $content.Substring($first, $second - $first).TrimEnd() + "`r`n"
        Write-Host "Duplicate takror.py blok olib tashlandi." -ForegroundColor Yellow
    }
}

# 2) mojibake matnlarni ASCII-safe regexlar bilan tuzatish
$replacements = @(
    @{ P = '(?m)^.*Q\.M \(izoh\) kiriting\. Masalan: kb$'; R = "\U0001F4DD Q.M (izoh) kiriting. Masalan: kb" },
    @{ P = '(?m)^.*Rangini kiriting\. Kerak bo''lmasa - deb yozing$'; R = "\U0001F3A8 Rangini kiriting. Kerak bo'lmasa - deb yozing" },
    @{ P = '(?m)^.*Sonini kiriting\. Masalan: 3000 sh yoki 3000 d$'; R = "\U0001F522 Sonini kiriting. Masalan: 3000 sh yoki 3000 d" },
    @{ P = '(?m)^.*Narxini kiriting\. Masalan: 450$'; R = "\U0001F4B0 Narxini kiriting. Masalan: 450" },
    @{ P = '(?m)^.*Topilgan tovar rasmi$'; R = "\U0001F5BC Topilgan tovar rasmi" },
    @{ P = '(?m)^.*Takror: tovar nomini yozing\.$'; R = "\U0001F501 Takror: tovar nomini yozing." },
    @{ P = '(?m)^.*Brend yoki mijoz yoki telefon yozing\.$'; R = "\U0001F3F7 Brend yoki mijoz yoki telefon yozing." }
)

foreach ($item in $replacements) {
    $content = [regex]::Replace($content, $item.P, $item.R)
}

# 3) oldingi injected fixni olib tashlash
$content = [regex]::Replace(
    $content,
    '(?s)# ===== TAKROR_TEXT_IMAGE_EDIT_FIX =====.*?# ===== /TAKROR_TEXT_IMAGE_EDIT_FIX =====\s*',
    ''
)

# 4) TK_REVIEW state bo'lmasa qo'shamiz
$content = [regex]::Replace(
    $content,
    'TK_SEARCH,\s*TK_PICK,\s*TK_EXTRA,\s*TK_QTY,\s*TK_EDIT_VALUE\s*=\s*range\(5\)',
    'TK_SEARCH, TK_PICK, TK_EXTRA, TK_QTY, TK_REVIEW, TK_EDIT_VALUE = range(6)'
)

# 5) ASCII-safe python append block
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
        f"\U0001F3F7 {_tk_safe_text(d.get('brand')).upper()}",
        f"\U0001F9FE {_tk_safe_text(d.get('item_type'))}",
        f"\U0001F4CF {_tk_safe_text(d.get('size'))}",
        f"\U0001F4DD {_tk_safe_text(d.get('qm_note'))}",
    ]

    bg = _tk_safe_text(d.get("bg_color"), "")
    if bg:
        lines.append(f"\U0001F3A8 {bg}")

    lines.extend([
        f"\U0001F522 {qty_show or '-'}",
        f"\U0001F4B0 {_fmt_num(d.get('price_uzs'))}",
        f"\U0001F4CA {_tk_safe_text(d.get('channel_name'), 'Zakariyo 02')}",
        f"\U0001F4C1 {_tk_safe_text(d.get('group_name'), 'karobka')}",
        "\U0001F3EC Abusahiy 75",
        f"\U0001F552 {moment_show}",
    ])
    return "\n".join(lines)


async def _tk_send_preview_fixed(target_message, context: ContextTypes.DEFAULT_TYPE):
    text = _tk_preview_text_fixed(context)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2705 Tasdiqlash", callback_data="tkr:ok")],
        [InlineKeyboardButton("\u270F\uFE0F Tahrirlash", callback_data="tkr:edit")],
        [InlineKeyboardButton("\u274C Bekor qilish", callback_data="tkr:cancel")],
    ])
    await target_message.reply_text(text, reply_markup=kb)
    return TK_REVIEW

# ===== /TAKROR_TEXT_IMAGE_EDIT_FIX =====
'@

$content = $content.TrimEnd() + "`r`n" + $append + "`r`n"
Set-Content $path $content -Encoding UTF8

Write-Host "Takror text/image/edit fix yozildi." -ForegroundColor Green
Write-Host "Keyin ishga tushiring:" -ForegroundColor Yellow
Write-Host "python -m app.main"
