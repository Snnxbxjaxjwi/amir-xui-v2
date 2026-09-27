"""All user-facing text + keyboards."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config

APP = "⚡️ AMIR X-UI V2 ⚡️"
TOP = "╔══════════════════════╗"
MID = "╠══════════════════════╣"
BOT = "╚══════════════════════╝"
S = "║"

def hdr(sub=""):
    h = f"{TOP}\n{S}  <b>{APP}</b>  {S}\n"
    if sub:
        h += f"{S}  <i>{sub}</i>  {S}\n"
    return h + BOT

MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("👤 اکانت‌ها", callback_data="sec_account"),
     InlineKeyboardButton("🚀 دپلوی", callback_data="sec_deploy")],
    [InlineKeyboardButton("🛰 TCP Proxy", callback_data="sec_tcp"),
     InlineKeyboardButton("🔌 پروتکل‌ها", callback_data="sec_proto")],
    [InlineKeyboardButton("📧 Fake Mail", callback_data="sec_fakemail")],
])

def welcome(name="", account=""):
    who = f"، {name}" if name else ""
    badge = (f"👤 اکانت فعال: <b>{account}</b>\n" if account
             else "⚪️ اکانتی ثبت نشده — بخش 👤 اکانت‌ها\n")
    return (f"{hdr(f'سلام{who} 👋')}\n\n{badge}"
            "🎛 مدیریت کامل 3x-ui روی Railway\n\n"
            f"{MID}\n👇 انتخاب کن:")

NOT_CONNECTED = (f"{hdr('قفل 🔒')}\n\n"
                 "اول از بخش 👤 <b>اکانت‌ها</b> یه اکانت Railway اضافه کن.\n\n"
                 f"{BOT}")

HELP = (f"{hdr('راهنما 📖')}\n\n"
        "👤 <b>اکانت‌ها</b> — چند توکن Railway، سوییچ آنی\n\n"
        "🚀 <b>دپلوی</b> — فلو ۴ مرحله‌ای:\n"
        "     1️⃣ دپلوی پنل‌ها + ۴ اینباند ws+tls هرکدوم\n"
        "     2️⃣ ⏸ مکث → ست ریجن توسط شما\n"
        "     3️⃣ 🌐 ست دامنه‌ها\n"
        "     4️⃣ 🔗 اتصال نودها\n\n"
        "🔌 <b>پروتکل‌ها</b> — ساخت اینباند ws+tls روی هر پنل\n\n"
        "📧 <b>Fake Mail</b> — ایمیل بفرست، آدرس فیک با پیشوند + می‌سازم\n\n"
        f"{MID}\n⚠️ بعد از افزودن اکانت، پیام حاوی توکن رو پاک کن 🗑")

# ── accounts ──
def accounts_text(accs, active):
    if not accs:
        body = "  (خالی)"
    else:
        body = "\n".join(
            f'{"🟢" if a["active"] else "⚪️"} <b>{a["label"]}</b>'
            + (f' · <code>{a["email"]}</code>' if a.get("email") else "")
            for a in accs)
    return f"{hdr('اکانت‌ها 👤')}\n\n{body}\n\n{MID}\n🟢 فعال: <b>{active or '—'}</b>"

def accounts_kb(accs):
    rows = []
    for a in accs:
        lbl = a["label"]
        if a["active"]:
            rows.append([InlineKeyboardButton(f"🟢 {lbl} (فعال)", callback_data="noop")])
        else:
            rows.append([InlineKeyboardButton(f"⚪️ سوییچ به {lbl}", callback_data=f"accsw:{lbl}"),
                         InlineKeyboardButton("🗑", callback_data=f"accdel:{lbl}")])
    rows.append([InlineKeyboardButton("➕ افزودن اکانت", callback_data="accadd")])
    rows.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")])
    return InlineKeyboardMarkup(rows)

ADD_ACCOUNT = ("{h}\n\n1️⃣ یه <b>اسم</b> بفرست (مثلاً <code>اصلی</code>)\n"
               "2️⃣ بعد <b>توکن Railway</b> رو بفرست\n\nلغو: /cancel")

# ── deploy ──
def deploy_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 شروع فلو کامل", callback_data="go_deploy")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")],
    ])

DEPLOY_WELCOME = (
    f"{hdr('دپلوی 🚀')}\n\n"
    "1️⃣ 📦 دپلوی پنل‌ها + ۴ اینباند ws+tls هر پنل\n"
    "2️⃣ ⏸ مکث → ریجن‌ها رو خودت ست می‌کنی\n"
    "3️⃣ 🌐 ادامه → دامنه‌ها ست میشن\n"
    "4️⃣ 🔗 ادامه → نودها وصل میشن\n\n"
    f"{MID}\n👇 آماده‌ای?")

STAGE2_PROMPT = ("✅ پنل‌ها و اینباندها آماده!\n\n"
                 "⏸ حالا وارد هر پنل شو و ریجن رو تنظیم کن:\n")

def stage2_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ست کردم — ادامه (دامنه‌ها)", callback_data="flow_domains")]])

def stage4_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 مرحله آخر — اتصال نودها", callback_data="flow_nodes")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")]])

# ── protocols ──
def proto_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 WS + TLS", callback_data="proto_pick")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")],
    ])

PROTO_WELCOME = (
    f"{hdr('پروتکل‌ها 🔌')}\n\n"
    "🌐 <b>WS + TLS</b>\n"
    "     └ VLESS + WebSocket + TLS\n"
    f"     └ پورت {config.IN_PORT} · مسیر {config.IN_PATH}\n\n"
    f"{MID}\n👇 انتخاب کن:")


# ── TCP proxy section ──
def tcp_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛰 چرخش TCP Proxy", callback_data="tcp_start")],
        [InlineKeyboardButton("📋 دامنه‌های پیشنهادی", callback_data="tcp_domains"),
         InlineKeyboardButton("⚙️ تنظیمات", callback_data="tcp_settings")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")],
    ])

TCP_WELCOME = (
    f"{hdr('TCP Proxy Manager 🛰')}\n\n"
    "چرخش TCP Proxy تا رسیدن به دامنه‌های خوش‌اسم\n"
    "(monorail, nozomi, kodama...)\n\n"
    "🔢 تعداد · 🔌 پورت · 🎯 حالت — از ⚙️ تنظیمات\n"
    "📋 لیست دامنه‌ها قابل ویرایشه\n\n"
    f"{MID}\n👇 انتخاب کن:")

def tcp_settings_text(p):
    mode = "🔀 دامنه‌های تأیید" if p.get("mode","good")=="good" else "🎲 رندم"
    return (f"{hdr('تنظیمات TCP ⚙️')}\n\n"
            f"🔢 تعداد برای هر پنل: <b>{p.get('count',2)}</b>\n"
            f"🔌 پورت شروع: <b>{p.get('port',443)}</b> (بعدی +۱)\n"
            f"🎯 حالت: {mode}\n\n{MID}\n👇 تغییر بده:")

def tcp_settings_kb(p):
    def mark(on): return "✅ " if on else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mark(p.get('count')==1)}1", callback_data="tcpset_count:1"),
         InlineKeyboardButton(f"{mark(p.get('count')==2)}2", callback_data="tcpset_count:2"),
         InlineKeyboardButton(f"{mark(p.get('count')==3)}3", callback_data="tcpset_count:3"),
         InlineKeyboardButton(f"{mark(p.get('count')==4)}4", callback_data="tcpset_count:4")],
        [InlineKeyboardButton(f"{mark(p.get('port')==443)}443", callback_data="tcpset_port:443"),
         InlineKeyboardButton(f"{mark(p.get('port')==8080)}8080", callback_data="tcpset_port:8080"),
         InlineKeyboardButton(f"{mark(p.get('port')==2053)}2053", callback_data="tcpset_port:2053")],
        [InlineKeyboardButton(f"{mark(p.get('mode','good')=='good')}🔀 تأیید", callback_data="tcpset_mode:good"),
         InlineKeyboardButton(f"{mark(p.get('mode')=='rnd')}🎲 رندم", callback_data="tcpset_mode:rnd")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="sec_tcp")],
    ])

def domains_text(domains):
    body = "\n".join(f"  {i}. <code>{d}</code>" for i,d in enumerate(domains,1))
    return (f"{hdr('دامنه‌های پیشنهادی 📋')}\n\n{body or '  (خالی)'}"
            f"\n\n{MID}\n📊 تعداد: <b>{len(domains)}</b>")

def domains_kb(domains):
    rows = []
    for d in domains[:12]:
        short = d.replace(".proxy.rlwy.net","")
        rows.append([InlineKeyboardButton(f"🗑 {short}", callback_data=f"tcpdel:{d}")])
    rows.append([InlineKeyboardButton("➕ افزودن", callback_data="tcpadd_hint"),
                 InlineKeyboardButton("🔄 پیش‌فرض", callback_data="tcpreset")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="sec_tcp")])
    return InlineKeyboardMarkup(rows)

# ── fake mail ──
FAKEMAIL_PROMPT = (
    f"{hdr('Fake Mail 📧')}\n\n"
    "ایمیلت رو بفرست تا آدرس فیکش رو بسازم:\n"
    "<code>Babaie640@gmail.com</code>\n"
    "    ⬇️\n"
    "<code>Babaie640+zephyr0427@gmail.com</code>\n\n"
    f"{MID}\nلغو: /cancel")

FAKEMAIL_BAD = (f"{hdr('ایمیل نامعتبر ⚠️')}\n\n"
                "فرمت درست: <code>name@example.com</code>\n"
                "ایمیل دیگه‌ای بفرست:")

def fakemail_result(alias):
    return (f"{hdr('Fake Mail 📧')}\n\n"
            f"🎮 <code>{alias}</code>\n\n"
            f"{MID}\n🔁 دکمه «یکی دیگه» یا هر ایمیل جدیدی بفرست")

def fakemail_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 یکی دیگه", callback_data="fmagain")],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")]])
