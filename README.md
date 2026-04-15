# reyting_kitob
Kitoblar reytingi

## 2 botni localda tez ishga tushirish (PowerShell)
Qo'lda uzun env yozib adashmaslik uchun 2 ta script qo'shildi:

- `run_order_local.ps1` → `order_bot` (`/kiritish`)
- `run_confirm_local.ps1` → `confirm_bot` (`/tasdiq`, `/takror`)

### 1) Order bot
```powershell
$ORDER_TOKEN = "<ORDER_BOT_TOKEN>"
$MS_TOKEN = "<MOYSKLAD_TOKEN>"

.\run_order_local.ps1 -OrderBotToken $ORDER_TOKEN -MoySkladToken $MS_TOKEN
```

### 2) Confirm bot
`GcpServiceAccountJson` ga to'liq service-account JSON matnini bering.

```powershell
$CONFIRM_TOKEN = "<CONFIRM_BOT_TOKEN>"
$MS_TOKEN = "<MOYSKLAD_TOKEN>"
$GCP_JSON = Get-Content .\service-account.json -Raw

.\run_confirm_local.ps1 `
  -ConfirmBotToken $CONFIRM_TOKEN `
  -MoySkladToken $MS_TOKEN `
  -GcpServiceAccountJson $GCP_JSON
```

### Ixtiyoriy parametrlar
Har ikki scriptda ham default `ProjectPath`:
`C:\Users\Jamshed_Artikov\zakbotbirka\app\zakariyoakabotlari`

Kerak bo'lsa override qiling:
```powershell
.\run_order_local.ps1 -OrderBotToken $ORDER_TOKEN -MoySkladToken $MS_TOKEN -ProjectPath "D:\mybot"
```

## Xavfsizlik
- Token va private key’larni chatga yubormang.
- Oshkor bo'lgan tokenlarni BotFather orqali `revoke` qiling.
