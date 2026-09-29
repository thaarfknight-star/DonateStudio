# دونیت استودیو — Donate Studio

برنامه‌ی دسکتاپ برای ساخت گیف‌های شفاف هشدار دونیت (مناسب اورلی استریم در
OBS / Streamlabs). هشت افکت آماده دارد، نام دونیت‌کننده و مبلغ را با فونت
**B Nazanin** روی یک پلاک تیره پایین گیف می‌نویسد و خروجی را به‌صورت گیف
شفاف (پس‌زمینه کاملاً شفاف) ذخیره می‌کند.

## اجرای نسخه‌ی سورس

```bash
pip install -r requirements.txt
python app.py
```

## ساخت فایل اجرایی ویندوز (روی سیستم ویندوز)

> کاربر نهایی هیچ‌چیز نصب نمی‌کند؛ همه‌ی وابستگی‌ها داخل پوشه‌ی خروجی باندل
> می‌شود. خروجی گیف فقط با Pillow ساخته می‌شود (بدون ffmpeg).

```bash
pip install -r requirements.txt
pip install pyinstaller
pyinstaller build.spec
```

خروجی: پوشه‌ی `dist/DonateStudio/` — فایل `DonateStudio.exe` را **همراه کل
پوشه** به سیستم مقصد منتقل کنید و اجرا کنید.

## تست headless

```bash
QT_QPA_PLATFORM=offscreen python smoke_test.py
```

## ساختار

- `donate_engine.py` — موتور رندر: ۸ افکت (`EFFECTS`)، تابع
  `render_frames(...)` و خروجی گیف شفاف `export_gif(...)` (فقط Pillow).
- `app.py` — رابط گرافیکی PySide6 (راست‌به‌چپ، تم تیره).
- `build.spec` — اسپک PyInstaller (onedir، بدون کنسول).
