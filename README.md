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

## Railway'da 2 ta botni bir vaqtda ishlatish
Bitta repositorydan 2 ta service ochiladi. Har ikkisining `Start Command` bir xil:

```bash
python -m app.main
```

### Service A: `order_bot`
`Variables` bo'limida:

- `APP_MODE=order_bot`
- `ORDER_BOT_TOKEN=<order token>`
- `MOYSKLAD_TOKEN=<moysklad token>`
- `MOYSKLAD_BASE_URL=https://api.moysklad.ru/api/remap/1.2`
- `MOYSKLAD_TZ=Europe/Moscow`
- `TG_TZ=Asia/Tashkent`
- `ADMIN_IDS=520559745`

Qo'ymaslik kerak (aralashmasin):
- `CONFIRM_BOT_TOKEN`
- `BOT_TOKEN`

### Service B: `confirm_bot`
`Variables` bo'limida:

- `APP_MODE=confirm_bot`
- `CONFIRM_BOT_TOKEN=<confirm token>`
- `CONFIRM_CHAT_ID=<chat id>`
- `REPEAT_CHAT_ID=<chat id>`
- `MOYSKLAD_TOKEN=<moysklad token>`
- `MOYSKLAD_BASE_URL=https://api.moysklad.ru/api/remap/1.2`
- `VISION_ENABLED=1`
- `GCP_SA_JSON=<service account json (single line)>`

Qo'ymaslik kerak (aralashmasin):
- `ORDER_BOT_TOKEN`
- `BOT_TOKEN`

### Deploy tartibi (tavsiya)
1. Avval `confirm_bot` service'ni deploy qiling va logda `Application started` ni tekshiring.
2. Keyin `order_bot` service'ni deploy qiling.
3. Har bir bot tokeni boshqasidan farq qilishini tekshiring (`getMe`).
4. Agar local test qilmoqchi bo'lsangiz, Railway'dagi shu token ishlatayotgan serviceni vaqtincha to'xtating.

## Xavfsizlik
- Token va private key’larni chatga yubormang.
- Oshkor bo'lgan tokenlarni BotFather orqali `revoke` qiling.
