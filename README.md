# ⚡️ Amir X-UI V2

ربات تلگرامی مدیریت 3x-ui روی Railway — با فلو دپلوی ۴ مرحله‌ای و بخش پروتکل‌ها.

## 🧭 بخش‌ها

### 👤 اکانت‌ها
چند توکن Railway، سوییچ آنی، حذف — دائمی ذخیره میشه.

### 🚀 دپلوی (فلو ۴ مرحله‌ای)
1. 📦 دپلوی پنل‌ها + ساخت **۱ اینباند ws+tls با ۴ کلاینت/لینک** برای هر پنل (محدودیت Xray: هر پورت فقط یک اینباند)
2. 🌍 **ریجن‌ها** — تلاش خودکار طبق `PANEL_REGIONS` (NL/NL_MT→هلند `ams`، US_V→ویرجینیا `iad`، SG→سنگاپور `sin`)؛ اگر پلَن Railway منطقه رو نپذیره، هشدار «ثبت نشد» نشون داده میشه
3. 🌐 با زدن «ادامه» → ست خودکار دامنه‌ها (پورت 3000)
4. 🔗 اتصال همه نودها به پنل اصلی

### 🔌 پروتکل‌ها
- **WS + TLS** — VLESS + WebSocket + TLS (همون مشخصات amir_xu: پورت 8080، مسیر /cdn)

### 📧 Fake Mail
ایمیل بفرست (`name@example.com`) → آدرس فیک با پیشوند `+` و کلمه/عدد رندم:
`Babaie640@gmail.com` → `Babaie640+zephyr0427@gmail.com`

## 📱 دستورات
| دستور | کار |
|---|---|
| `/start` | منوی اصلی |
| `/help` | هم‌معادل `/start` |
| `/cancel` | لغو عملیات جاری |

## 🚀 راه‌اندازی
```bash
pip install -r requirements.txt
export BOT_TOKEN="..."
python bot.py
```

## 🧩 معماری
```
bot.py            ورودی + هندلرها + روتر کال‌بک
wizard.py         فلو دپلوی ۴ مرحله‌ای (state machine)
config.py         تنظیمات env-first
ui.py             متن‌ها و کیبوردها
railway.py        کلاینت GraphQL Railway
xui.py            کلاینت 3x-ui (اینباند/نود/لینک)
tcp.py            چرخش TCP Proxy روی دامنه‌های خوب
tcp_state.py      دامنه‌های پیشنهادی + تنظیمات کاربران
accounts.py       مدیریت چند اکانت (JSON در DATA_DIR)
errors.py         خطاهای تایپ‌شده با پیام فارسی
Dockerfile        برای Railway
```
