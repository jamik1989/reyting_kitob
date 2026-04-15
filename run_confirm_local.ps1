param(
    [Parameter(Mandatory=$true)][string]$ConfirmBotToken,
    [Parameter(Mandatory=$true)][string]$MoySkladToken,
    [Parameter(Mandatory=$true)][string]$GcpServiceAccountJson,
    [string]$ProjectPath = "C:\Users\Jamshed_Artikov\zakbotbirka\app\zakariyoakabotlari",
    [string]$ConfirmChatId = "-1002880207467",
    [string]$RepeatChatId = "-1002880207467",
    [string]$MoySkladBaseUrl = "https://api.moysklad.ru/api/remap/1.2",
    [ValidateSet("0","1")][string]$VisionEnabled = "1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $ProjectPath

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    . .\.venv\Scripts\Activate.ps1
}

$env:APP_MODE = "confirm_bot"
$env:CONFIRM_BOT_TOKEN = $ConfirmBotToken
$env:CONFIRM_CHAT_ID = $ConfirmChatId
$env:REPEAT_CHAT_ID = $RepeatChatId
$env:MOYSKLAD_TOKEN = $MoySkladToken
$env:MOYSKLAD_BASE_URL = $MoySkladBaseUrl
$env:VISION_ENABLED = $VisionEnabled

# Normalize JSON to one-line to avoid quoting issues in env var.
$gcpObj = $GcpServiceAccountJson | ConvertFrom-Json
$env:GCP_SA_JSON = $gcpObj | ConvertTo-Json -Compress

Remove-Item Env:ORDER_BOT_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:BOT_TOKEN -ErrorAction SilentlyContinue

Write-Host "[confirm_bot] token check..."
Invoke-RestMethod "https://api.telegram.org/bot$env:CONFIRM_BOT_TOKEN/getMe" | Out-Null

Write-Host "[confirm_bot] starting python -m app.main"
python -m app.main
