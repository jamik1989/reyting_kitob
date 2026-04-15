param(
    [Parameter(Mandatory=$true)][string]$OrderBotToken,
    [Parameter(Mandatory=$true)][string]$MoySkladToken,
    [string]$ProjectPath = "C:\Users\Jamshed_Artikov\zakbotbirka\app\zakariyoakabotlari",
    [string]$MoySkladBaseUrl = "https://api.moysklad.ru/api/remap/1.2",
    [string]$MoySkladTz = "Europe/Moscow",
    [string]$TgTz = "Asia/Tashkent",
    [string]$AdminIds = "520559745"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectPath

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
}

$env:APP_MODE = "order_bot"
$env:ORDER_BOT_TOKEN = $OrderBotToken
$env:MOYSKLAD_TOKEN = $MoySkladToken
$env:MOYSKLAD_BASE_URL = $MoySkladBaseUrl
$env:MOYSKLAD_TZ = $MoySkladTz
$env:TG_TZ = $TgTz
$env:ADMIN_IDS = $AdminIds

Remove-Item Env:CONFIRM_BOT_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:BOT_TOKEN -ErrorAction SilentlyContinue

Write-Host "[order_bot] token check..."
Invoke-RestMethod "https://api.telegram.org/bot$env:ORDER_BOT_TOKEN/getMe" | Out-Null

Write-Host "[order_bot] starting python -m app.main"
python -m app.main
