param(
    [string]$ProjectPath = (Get-Location).Path,
    [string]$TargetRelativePath = "app/handlers/takror.py",
    [string]$SourceRelativePath = "takror_clean.py",
    [switch]$NoBackup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-InProjectPath {
    param([string]$BasePath, [string]$RelativePath)
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $RelativePath))
}

if (-not (Test-Path -LiteralPath $ProjectPath)) {
    throw "ProjectPath topilmadi: $ProjectPath"
}

$sourcePath = Resolve-InProjectPath -BasePath $ProjectPath -RelativePath $SourceRelativePath
$targetPath = Resolve-InProjectPath -BasePath $ProjectPath -RelativePath $TargetRelativePath

if (-not (Test-Path -LiteralPath $sourcePath)) {
    throw "Source fayl topilmadi: $sourcePath"
}

if (-not (Test-Path -LiteralPath $targetPath)) {
    throw "Target fayl topilmadi: $targetPath"
}

if (-not $NoBackup) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backup = "$targetPath.bak_allinone_$stamp"
    Copy-Item -LiteralPath $targetPath -Destination $backup -Force
    Write-Host "Backup yaratildi: $backup"
}

$content = Get-Content -LiteralPath $sourcePath -Raw

# UTF-8 (without BOM) yozish
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($targetPath, $content, $utf8NoBom)

Write-Host "OK: $TargetRelativePath yangilandi ($SourceRelativePath dan)."

$checks = @(
    'TK_SEARCH, TK_PICK, TK_EXTRA, TK_QTY, TK_REVIEW, TK_EDIT_VALUE = range\(6\)',
    'timeout=\(4, 8\)',
    'to_thread\(_get_repeat_product_image',
    'tk_cp_api_forbidden',
    '_create_customerorder_fallback'
)

Write-Host ""
Write-Host "Verification:"
foreach ($p in $checks) {
    $hit = Select-String -Path $targetPath -Pattern $p -SimpleMatch:$false
    if ($hit) {
        Write-Host "  ✅ found: $p"
    } else {
        Write-Warning "  ❌ missing: $p"
    }
}

Write-Host ""
Write-Host "Keyingi qadam:"
Write-Host "  1) python -m app.main"
Write-Host "  2) /takror ni qayta test qiling"
Write-Host "  3) xato bo'lsa to'liq traceback/log yuboring"
