param(
    [Parameter(Mandatory=$true)][string]$OrderBotToken,
    [Parameter(Mandatory=$true)][string]$MoySkladToken,
    [string]$ProjectPath = (Get-Location).Path,
    [string]$MoySkladBaseUrl = "https://api.moysklad.ru/api/remap/1.2",
    [string]$MoySkladTz = "Europe/Moscow",
    [string]$TgTz = "Asia/Tashkent",
    [string]$AdminIds = "520559745"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ProjectPath)) {
    throw "ProjectPath not found: $ProjectPath"
}

Set-Location $ProjectPath

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
} else {
    Write-Warning "Virtual environment activation script not found (.venv\\Scripts\\Activate.ps1). Continuing with current Python."
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python command not found in PATH"
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
$tokenCheck = Invoke-RestMethod "https://api.telegram.org/bot$($env:ORDER_BOT_TOKEN)/getMe"
if (-not $tokenCheck.ok) {
    throw "Telegram token check failed for ORDER_BOT_TOKEN"
}
Write-Host "[order_bot] token valid: @$($tokenCheck.result.username)"

Write-Host "[order_bot] starting python -m app.main"
python -m app.main
