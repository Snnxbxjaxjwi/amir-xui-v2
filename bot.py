"""
Amir X-UI V2 — entry point. Thin handlers; logic in wizard.py.
"""
import asyncio
import logging
import os
import uuid

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                          ContextTypes, MessageHandler, filters)

import config, ui
import fake_mail
from accounts import Accounts
from tcp import TCPProxy, normalize_domains
from tcp_state import TCPState
from errors import AppError, PanelError
from railway import Railway
from wizard import Wizard

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("amir-v2")

ACC = Accounts(os.path.join(config.DATA_DIR, "accounts.json"))
TCP = TCPState()


# ── helpers ──
def token_of(ctx):
    return ctx.user_data.get("_tok") or ""


def origin(update: Update):
    if update.message:
        return update.message
    if update.callback_query:
        return update.callback_query.message
    return None


async def safe_edit(qmsg, text, keyboard=None):
    try:
        await qmsg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        pass

say = safe_edit  # TCP progress: guarded edit of the status message



# ── commands ──
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    acc, lbl = ACC.get(uid)
    ctx.user_data["_tok"] = acc["token"] if acc else ""
    await update.message.reply_text(
        ui.welcome(update.effective_user.first_name or "", lbl),
        reply_markup=ui.MENU, parse_mode="HTML")


async def cmd_cancel(update, ctx):
    uid = update.effective_user.id
    st = ctx.user_data.setdefault(uid, {})
    cleared = any([st.pop("await_acc_label", False),
                   st.pop("await_domain", False),
                   st.pop("await_fakemail", False)])
    wiz = ctx.bot_data.pop(f"wiz_{uid}", None)
    if wiz and wiz.state != "idle":
        wiz.state = "idle"
        await update.message.reply_text("🛑 عملیات لغو شد.", parse_mode="HTML")
    elif cleared:
        await update.message.reply_text(ui.hdr("لغو شد ❌"), parse_mode="HTML")
    else:
        await update.message.reply_text("چیزی برای لغو نبود.")


async def on_text(update, ctx):
    uid = update.effective_user.id
    st = ctx.user_data.setdefault(uid, {})

    if st.pop("await_fakemail", False):
        email = update.message.text.strip()
        if not fake_mail.is_email(email):
            st["await_fakemail"] = True
            await update.message.reply_text(ui.FAKEMAIL_BAD, parse_mode="HTML")
            return
        st["last_fm"] = email
        await update.message.reply_text(
            ui.fakemail_result(fake_mail.make_alias(email)),
            reply_markup=ui.fakemail_kb(), parse_mode="HTML")
        return

    if st.pop("await_domain", False):
        d = update.message.text.strip()
        okk = TCP.add_domain(d)
        ds = TCP.domains()
        msg = f"✅ <code>{d}</code> اضافه شد." if okk else f"⚠️ <code>{d}</code> قبلاً هست."
        await update.message.reply_text(
            ui.domains_text(ds) + f"\n\n{msg}",
            reply_markup=ui.domains_kb(ds), parse_mode="HTML")
        return

    if st.pop("await_acc_label", False):
        st["pending_label"] = update.message.text.strip()[:32]
        await update.message.reply_text(
            ui.ADD_ACCOUNT.replace(
                "{h}", ui.hdr(f"اکانت «{st['pending_label']}» ➕"))
            + "\n\n🔑 حالا <b>توکن</b> رو بفرست:", parse_mode="HTML")
        return

    if "pending_label" in st:
        label = st.pop("pending_label")
        token = update.message.text.strip()
        msg = await update.message.reply_text(
            ui.hdr("در حال بررسی... 🔍"), parse_mode="HTML")
        try:
            api = Railway(token)
            ws, email = await asyncio.to_thread(api.whoami)
            if not ACC.add(uid, label, token, email):
                await safe_edit(msg, ui.hdr("تکراری ⚠️") + f"\n\nاسم {label} هست.")
                return
            ctx.user_data["_tok"] = token
            accs = ACC.list(uid)
            await safe_edit(msg,
                            f"{ui.hdr('اکانت اضافه شد ✅')}\n\n"
                            f"👤 {label} · <code>{email}</code>",
                            keyboard=ui.accounts_kb(accs))
        except AppError as e:
            await safe_edit(msg, f"{ui.hdr('⛔️')}\n\n{e.user_msg}")


# ════════════════════════ ACCOUNTS ════════════════════════
async def show_accounts(update, ctx, q):
    uid = update.effective_user.id
    await q.edit_message_text(ui.accounts_text(ACC.list(uid), ACC.active_label(uid)),
                              reply_markup=ui.accounts_kb(ACC.list(uid)),
                              parse_mode="HTML")


async def do_accounts(update, ctx, q, data):
    uid = update.effective_user.id
    if data == "accadd":
        ctx.user_data.setdefault(uid, {})["await_acc_label"] = True
        await q.edit_message_text(
            ui.ADD_ACCOUNT.replace("{h}", ui.hdr("افزودن اکانت ➕")),
            parse_mode="HTML")
    elif data.startswith("accsw:"):
        lbl = data.split(":", 1)[1]
        ACC.switch(uid, lbl)
        # refresh token in user_data
        acc, _ = ACC.get(uid)
        ctx.user_data["_tok"] = acc["token"] if acc else ""
        await show_accounts(update, ctx, q)
    elif data.startswith("accdel:"):
        lbl = data.split(":", 1)[1]
        ACC.remove(uid, lbl)
        acc, _ = ACC.get(uid)
        ctx.user_data["_tok"] = acc["token"] if acc else ""
        await show_accounts(update, ctx, q)


# ════════════════════════ DEPLOY WIZARD ════════════════════════
async def start_deploy(update, ctx, q):
    uid = update.effective_user.id
    acc, _ = ACC.get(uid)
    if not acc:
        await q.edit_message_text(ui.NOT_CONNECTED, parse_mode="HTML")
        return
    ctx.user_data["_tok"] = acc["token"]
    api = Railway(acc["token"])

    async def status_cb(text):
        try:
            await q.edit_message_text(text, parse_mode="HTML")
        except Exception:
            pass

    wiz = Wizard(api)
    ctx.bot_data[f"wiz_{uid}"] = wiz

    ok = await wiz.deploy(status_cb)
    if not ok:
        await safe_edit(q.message, f"{ui.hdr('دپلوی ناموفق ⛔️')}\n\n{wiz.error}")
        return

    def reg_line(p):
        want, got = p.get("region_want"), p.get("region")
        if not want:
            return None
        if got == want:
            return f"  🌍 <b>{p['name']}</b> → <code>{got}</code> ✅"
        return f"  🌍 <b>{p['name']}</b> → <code>{want}</code> ⚠️ ثبت نشد"
    reg_lines = [x for x in (reg_line(p) for p in wiz.panels) if x]
    if reg_lines and all("ثبت نشد" in x for x in reg_lines):
        reg_lines.append("\n⚙️ پلن فعلی Railway تغییر منطقه رو نپذیرفت؛ با پلن پولی اعمال میشه.")
    panel_list = "\n".join(
        f"  🌐 <code>{p['url'].replace('https://', '')}/managepanel/</code>"
        for p in wiz.panels if p.get("url"))
    body = "\n".join(reg_lines) or "  (برای پنل‌های سفارشی ریجنی تعریف نشده)"
    body += ("\n" + panel_list) if panel_list else ""
    await q.edit_message_text(
        f"{ui.hdr('مرحله ۲/۴ — ریجن‌ها 🌍')}\n{ui.MID}\n"
        + ui.STAGE2_PROMPT + body
        + f"\n\n{ui.BOT}\n👇 ادامه بده:",
        reply_markup=ui.stage2_kb(), parse_mode="HTML")


async def stage_domains(update, ctx, q):
    uid = update.effective_user.id
    wiz = ctx.bot_data.get(f"wiz_{uid}")
    if not wiz or wiz.state == "idle":
        await q.edit_message_text(ui.hdr("فلو فعالی نیست 📭"), parse_mode="HTML")
        return

    async def status_cb(text):
        try:
            await q.edit_message_text(text, parse_mode="HTML")
        except Exception:
            pass

    ok = await wiz.set_domains(status_cb)
    await q.edit_message_text(
        f"{ui.hdr(f'دامنه‌ها ست شدن ✅ ({ok}/{len(wiz.panels)})')}\n{ui.MID}\n"
        + "\n".join(f"{'✅' if p['status']=='SUCCESS' else '⚠️'} <b>{p['name']}</b>"
                    for p in wiz.panels)
        + f"\n\n{ui.BOT}\n👇 مرحله آخر:",
        reply_markup=ui.stage4_kb(), parse_mode="HTML")


async def stage_nodes(update, ctx, q):
    uid = update.effective_user.id
    wiz = ctx.bot_data.get(f"wiz_{uid}")
    if not wiz:
        await q.edit_message_text(ui.hdr("فلو فعالی نیست 📭"), parse_mode="HTML")
        return

    async def status_cb(text):
        try:
            await q.edit_message_text(text, parse_mode="HTML")
        except Exception:
            pass

    lines = await wiz.link_nodes(status_cb)
    await q.edit_message_text(
        f"{ui.hdr('همه نودها متصل شدن 🎉')}\n{ui.MID}\n" + "\n".join(lines),
        parse_mode="HTML")


# ════════════════════════ PROTOCOLS ════════════════════════
async def show_proto(update, ctx, q):
    await q.edit_message_text(ui.PROTO_WELCOME, reply_markup=ui.proto_menu(),
                              parse_mode="HTML")


async def do_proto(update, ctx, q, data):
    uid = update.effective_user.id
    deployed = [p for p in (ctx.bot_data.get(f"wiz_{uid}").panels
                            if ctx.bot_data.get(f"wiz_{uid}") else [])
                if p.get("url")]
    if data == "proto_pick":
        if not deployed:
            await q.edit_message_text(
                f"{ui.hdr('پنلی نیست 📭')}\n\nاول دپلوی کن: 🚀 بخش دپلوی",
                parse_mode="HTML")
            return
        rows = [[InlineKeyboardButton(p["name"],
                 callback_data=f"wstls:{p['name']}:{p['url']}")] for p in deployed]
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="sec_proto")])
        await q.edit_message_text(ui.hdr("WS+TLS روی کدوم پنل؟ 🌐"),
                                  reply_markup=InlineKeyboardMarkup(rows),
                                  parse_mode="HTML")
        return

    if data.startswith("wstls:"):
        _, name, url = data.split(":", 2)
        msg = await _qmsg(update).reply_text(
            ui.hdr(f"ساخت ws+tls روی {name}... 🔌"), parse_mode="HTML")

        def work():
            from xui import Panel, vless_link
            c = Panel(url)
            if not c.login():
                raise PanelError("ورود به پنل ناموفق")
            u = str(uuid.uuid4())
            r = c.create_ws_tls_inbound(uuid=u, email=f"{name.lower()}-user",
                                        domain=url.replace("https://", ""),
                                        port=config.IN_PORT, path=config.IN_PATH)
            if not r.get("success"):
                raise PanelError(r.get("msg", "خطا"))
            return vless_link(url, u, config.IN_PATH, f"Amir-{name}")

        try:
            link = await asyncio.to_thread(work)
            await safe_edit(msg,
                            f"{ui.hdr(f'sاخته شد ✅ — {name}')}\n\n"
                            f"🔌 {config.IN_PORT} · 🛣 {config.IN_PATH} · 🔐 TLS"
                            f"\n\n<code>{link}</code>\n\n"
                            "📲 کپی → v2rayNG → Import")
        except PanelError as e:
            await safe_edit(msg, f"{ui.hdr('خطا ⛔️')}\n\n{e.user_msg}")


def _qmsg(update):
    return update.callback_query.message if update.callback_query else update.message



# ════════════════════════ TCP PROXY ════════════════════════
async def show_tcp(update, ctx, q):
    await q.edit_message_text(ui.TCP_WELCOME, reply_markup=ui.tcp_menu(),
                              parse_mode="HTML")


def _panels_for(ctx, uid):
    wiz = ctx.bot_data.get(f"wiz_{uid}")
    return [p for p in (wiz.panels if wiz else []) if p.get("sid")] if wiz else []


async def start_tcp(update, ctx, q):
    uid = update.effective_user.id
    panels = _panels_for(ctx, uid)
    if not panels:
        # rediscover from newest project
        tok = token_of(ctx)
        if not tok:
            await q.edit_message_text(ui.NOT_CONNECTED, parse_mode="HTML")
            return
        from railway import Railway
        api = Railway(tok)
        try:
            projs = await asyncio.to_thread(api.projects)
            if not projs:
                await q.edit_message_text(ui.hdr("پروژه‌ای نیست 📭"), parse_mode="HTML")
                return
            proj = projs[0]
            svcs = []
            # list services via project query
            d = api.gql("""query($id:String!){project(id:$id){
                services(first:10){edges{node{id name}}}}}""", {"id": proj["id"]})
            for e in d["project"]["services"]["edges"]:
                svcs.append({"name": e["node"]["name"], "sid": e["node"]["id"],
                             "url": "", "status": "WAITING"})
            wiz = Wizard(api)
            wiz.panels = svcs
            ctx.bot_data[f"wiz_{uid}"] = wiz
            panels = svcs
        except Exception as e:
            await q.edit_message_text(f"{ui.hdr('خطا ⛔️')}\n\n❌ {e}", parse_mode="HTML")
            return

    rows = [[InlineKeyboardButton(p["name"], callback_data=f"tcpsvc:{p['sid']}:{p['name']}")]
            for p in panels]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="sec_tcp")])
    await q.edit_message_text(ui.hdr("چرخش TCP روی کدوم پنل؟ 🛰"),
                              reply_markup=InlineKeyboardMarkup(rows),
                              parse_mode="HTML")


async def run_tcp_panel(update, ctx, q, sid, name):
    uid = update.effective_user.id
    acc, _ = ACC.get(uid)
    if not acc:
        await q.edit_message_text(ui.NOT_CONNECTED, parse_mode="HTML")
        return
    api = Railway(acc["token"])
    env_id = ""
    pid = ctx.user_data.get("_proj_id") or ""
    if pid:
        env_id = await asyncio.to_thread(api.first_env, pid)

    prefs = TCP.prefs(uid)
    count = int(prefs.get("count", 2))
    port = int(prefs.get("port", 443))
    mode = prefs.get("mode", "good")
    targets = normalize_domains(",".join(TCP.domains())) if mode == "good" else None

    stop = {"kill": False}
    ctx.bot_data[f"tcpstop_{uid}"] = stop
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 توقف", callback_data="tcp_stop")]])

    status = await _qmsg(update).reply_text(
        ui.hdr(f"چرخش {name} — پروکسی ۱/{count} 🛰"), parse_mode="HTML",
        reply_markup=kb)

    results = []
    lines = []

    def on_progress(m): lines.append(m)

    # assign unique ports: base, +1, ...
    used = set()
    try:
        tcp_api = TCPProxy(acc["token"])
        existing = await asyncio.to_thread(tcp_api.list, sid, env_id)
        used = {p.get("applicationPort") for p in existing
                if p.get("applicationPort")}
    except Exception:
        pass
    ports, cand = [], port
    while len(ports) < count:
        if cand not in used: ports.append(cand)
        cand += 1

    for i in range(1, count + 1):
        port_i = ports[i-1]
        lines.clear()
        await say(status,
                  ui.hdr(f"🛰 {name} — پروکسی {i}/{count}")
                  + f"\n\n<pre>{lines[-6:] and chr(10).join(lines[-6:]) or 'شروع...'}</pre>"
                  + f"\n\n🎯 {'🔀 تأیید' if mode=='good' else '🎲 رندم'} · 🔌 پورت {port_i}",
                  keyboard=kb)

        def work():
            t = TCPProxy(acc["token"])
            return t.rotate(sid, env_id, port_i, targets=targets,
                            max_tries=30, cooldown=8, on_progress=on_progress,
                            cancel=lambda: stop["kill"])
        try:
            res = await asyncio.wait_for(asyncio.to_thread(work), timeout=900)
        except Exception as e:
            res = None; lines.append(f"خطا: {e}")

        if res:
            dom, prt = res
            results.append((name, f"{dom}:{prt}"))
            await say(status, f"{ui.hdr(f'✅ {name} — {i}/{count}')}"
                              f"\n\n🎯 <code>{dom}:{prt}</code>")
        else:
            if stop.get("kill"): break
            results.append((name, "❌ به هدف نرسید"))

    ctx.bot_data.pop(f"tcpstop_{uid}", None)
    summary = "\n".join(
        f"{'✅' if '❌' not in v else '❌'} <b>{n}</b> → <code>{v}</code>"
        for n, v in results)
    await say(status, f"{ui.hdr('نتیجه TCP Proxy 🛰')}\n{ui.MID}\n{summary}")


async def handle_tcp(update, ctx, q, data):
    uid = update.effective_user.id

    if data == "sec_tcp":
        await show_tcp(update, ctx, q); return
    if data == "tcp_start":
        await start_tcp(update, ctx, q); return
    if data == "tcp_settings":
        await q.edit_message_text(ui.tcp_settings_text(TCP.prefs(uid)),
                                  reply_markup=ui.tcp_settings_kb(TCP.prefs(uid)),
                                  parse_mode="HTML")
        return
    if data.startswith("tcpset_"):
        kind, _, val = data.partition(":")
        field = {"tcpset_count":"count","tcpset_port":"port","tcpset_mode":"mode"}[kind]
        TCP.set_pref(uid, **{field: int(val) if field != "mode" else val})
        p = TCP.prefs(uid)
        await q.edit_message_text(ui.tcp_settings_text(p),
                                  reply_markup=ui.tcp_settings_kb(p), parse_mode="HTML")
        return
    if data == "tcp_domains":
        ds = TCP.domains()
        await q.edit_message_text(ui.domains_text(ds),
                                  reply_markup=ui.domains_kb(ds), parse_mode="HTML")
        return
    if data.startswith("tcpdel:"):
        TCP.remove_domain(data.split(":",1)[1])
        ds = TCP.domains()
        await q.edit_message_text(ui.domains_text(ds),
                                  reply_markup=ui.domains_kb(ds), parse_mode="HTML")
        return
    if data == "tcpreset":
        TCP.reset_domains(); ds = TCP.domains()
        await q.edit_message_text(ui.domains_text(ds),
                                  reply_markup=ui.domains_kb(ds), parse_mode="HTML")
        return
    if data == "tcpadd_hint":
        ctx.user_data.setdefault(uid, {})["await_domain"] = True
        await q.edit_message_text(
            f"{ui.hdr('افزودن دامنه ➕')}\n\nاسم دامنه رو بفرست:\n"
            "<code>mybox</code> یا <code>mybox.proxy.rlwy.net</code>\n\nلغو: /cancel",
            parse_mode="HTML")
        return
    if data == "tcp_stop":
        stop = ctx.bot_data.get(f"tcpstop_{uid}")
        if stop: stop["kill"] = True; await q.answer("در حال توقف… 🛑")
        else: await q.answer("چرخشی در جریان نیست", show_alert=True)
        return
    if data.startswith("tcpsvc:"):
        _, sid, name = data.split(":", 2)
        await run_tcp_panel(update, ctx, q, sid, name)
        return


# ════════════════════════ FAKE MAIL ════════════════════════
FM_BACK = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔙 منوی اصلی", callback_data="refresh_menu")]])


async def fakemail_start(update, ctx, q):
    ctx.user_data.setdefault(update.effective_user.id, {})["await_fakemail"] = True
    try:
        await q.edit_message_text(ui.FAKEMAIL_PROMPT, reply_markup=FM_BACK,
                                  parse_mode="HTML")
    except Exception:
        pass


async def fakemail_again(update, ctx, q):
    uid = update.effective_user.id
    st = ctx.user_data.setdefault(uid, {})
    email = st.get("last_fm")
    if not email:
        st["await_fakemail"] = True
        try:
            await q.edit_message_text(ui.FAKEMAIL_PROMPT, reply_markup=FM_BACK,
                                      parse_mode="HTML")
        except Exception:
            pass
        return
    try:
        await q.edit_message_text(
            ui.fakemail_result(fake_mail.make_alias(email)),
            reply_markup=ui.fakemail_kb(), parse_mode="HTML")
    except Exception:
        pass


# ════════════════════════ ROUTER ════════════════════════
async def on_callback(update, ctx):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id

    if data == "refresh_menu":
        acc, lbl = ACC.get(uid)
        await q.edit_message_text(
            ui.welcome(update.effective_user.first_name or "", lbl),
            reply_markup=ui.MENU, parse_mode="HTML")
        return
    if data == "noop":
        await q.answer("این اکانت فعال ✅", show_alert=True)
        return
    if data == "sec_account":
        await show_accounts(update, ctx, q)
        return
    if data == "accadd" or data.startswith(("accsw:", "accdel:")):
        await do_accounts(update, ctx, q, data)
        return
    if data == "sec_deploy":
        await q.edit_message_text(ui.DEPLOY_WELCOME, reply_markup=ui.deploy_menu(),
                                  parse_mode="HTML")
        return
    if data == "go_deploy":
        await start_deploy(update, ctx, q)
        return
    if data == "flow_domains":
        await stage_domains(update, ctx, q)
        return
    if data == "flow_nodes":
        await stage_nodes(update, ctx, q)
        return
    if data == "sec_proto":
        await show_proto(update, ctx, q)
        return
    if data == "sec_fakemail":
        await fakemail_start(update, ctx, q)
        return
    if data == "fmagain":
        await fakemail_again(update, ctx, q)
        return
    if data == "sec_tcp" or data.startswith(("tcp", "tcpsvc:")):
        await handle_tcp(update, ctx, q, data)
        return
    if data.startswith(("proto_", "wstls:")):
        await do_proto(update, ctx, q, data)
        return


async def on_error(update, ctx):
    log.exception("Unhandled error", exc_info=ctx.error)
    e = ctx.error
    user_msg = getattr(e, "user_msg", None) or str(e)[:200]
    try:
        q = getattr(update, "callback_query", None)
        msg = getattr(update, "effective_message", None) or (q.message if q else None)
        if msg:
            await msg.reply_text(f"{ui.hdr('خطا ⛔️')}\n\n{user_msg}",
                                 parse_mode="HTML")
    except Exception:
        pass


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN required!")
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    log.info("Amir X-UI V2 (rebuilt) started")
    app.run_polling()


if __name__ == "__main__":
    main()
