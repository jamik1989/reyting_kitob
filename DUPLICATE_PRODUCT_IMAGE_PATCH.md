# Takrordagi tovar rasmi (duplicate image) uchun qayta yuborilgan patch

Quyida siz so‘ragan **takrordagi tovar rasmi bilan ishlaydigan** minimal patch namunasi bor.
Bu patchning maqsadi:

1. Bir xil rasm bir sessiyada qayta kelganda qayta ishlamaslik.
2. MoySklad’ga bir xil rasmni qayta upload qilmaslik.
3. Bot oqimini to‘xtatmaslik (attach xatolari soft-fail bo‘lishi).

---

## 1) `app/services/moysklad.py` — rasm upload dedupe

```python
# app/services/moysklad.py
import hashlib
from typing import Optional


def image_sha256(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


class MoySkladService:
    def __init__(self, client):
        self.client = client
        # process scope cache: hash -> href/id
        self._image_cache: dict[str, str] = {}

    def upload_product_image_once(self, image_bytes: bytes, filename: str) -> Optional[str]:
        """
        Bir xil rasm qayta kelsa, avvalgi natijani qaytaradi.
        Yangi bo‘lsa upload qiladi.
        """
        digest = image_sha256(image_bytes)

        if digest in self._image_cache:
            return self._image_cache[digest]

        try:
            file_ref = self.client.upload_file(image_bytes=image_bytes, filename=filename)
            self._image_cache[digest] = file_ref
            return file_ref
        except Exception:
            # Soft-fail: bot oqimi to‘xtamasin
            return None
```

---

## 2) `app/handlers/order.py` — bir xil rasmni sessiyada bloklash

```python
# app/handlers/order.py
import hashlib


def _photo_digest(photo_bytes: bytes) -> str:
    return hashlib.sha256(photo_bytes).hexdigest()


async def on_product_photo(message, state, ms_service):
    data = await state.get_data()
    seen = set(data.get("seen_photo_hashes", []))

    photo_bytes = await download_photo_bytes(message)  # existing helper
    digest = _photo_digest(photo_bytes)

    if digest in seen:
        await message.answer("Bu rasm avval yuborilgan. Boshqa rasm yoki keyingi qadamni yuboring.")
        return

    seen.add(digest)
    await state.update_data(seen_photo_hashes=list(seen))

    file_ref = ms_service.upload_product_image_once(photo_bytes, "product.jpg")

    # Attach bo‘lmasa ham order oqimi davom etadi
    if file_ref is None:
        await message.answer("Rasm saqlanmadi, lekin davom etamiz.")

    # existing flow continues...
```

---

## 3) `app/handlers/confirm.py` — attach xatolarini soft-fail qilish

```python
# app/handlers/confirm.py
async def attach_receipt_if_any(ms_service, image_bytes: bytes):
    try:
        file_ref = ms_service.upload_product_image_once(image_bytes, "receipt.jpg")
        return file_ref
    except Exception:
        return None


async def on_confirm(message, state, ms_service):
    # ... existing logic
    file_ref = await attach_receipt_if_any(ms_service, receipt_bytes)
    if file_ref is None:
        await message.answer("Chek rasmi biriktirilmadi, lekin tasdiqlash davom etdi.")
    # ... continue confirmation
```

---

## Qisqa izoh

- Bu patch duplicate rasm muammosini hash orqali hal qiladi.
- `upload` xatosi bo‘lsa bot jarayoni yiqilmaydi.
- Real loyihada cache’ni Redis yoki DB’da saqlash tavsiya qilinadi (restartdan keyin ham dedupe ishlashi uchun).
