"""
Deploy wizard — explicit 4-stage state machine, persisted per chat.

States:
  idle      → nothing running
  deploying → stage 1: create project/services + inbounds
  paused    → stage 2: waiting for user to set regions (button continue)
  domains   → stage 3: setting domains
  nodes     → stage 4: linking nodes

The wizard object lives in bot_data keyed by chat id; every step is resumable.
"""
import asyncio
import logging
import time
import uuid

import config
import requests
from errors import AppError, PanelError, LimitError
from railway import Railway
from xui import Panel

log = logging.getLogger(__name__)




# ── UI atoms ──
APP = "⚡️ AMIR X-UI V2 ⚡️"
TOP = "╔══════════════════════╗"
MID = "╠══════════════════════╣"
BOT = "╚══════════════════════╝"
S = "║"
ICONS = {"SUCCESS": "🟢", "FAILED": "🔴", "CRASHED": "💥",
         "DEPLOYING": "🟡", "BUILDING": "🟡", "WAITING": "⚪️"}


def _hdr(sub=""):
    h = f"{TOP}\n{S}  <b>{APP}</b>  {S}\n"
    if sub:
        h += f"{S}  <i>{sub}</i>  {S}\n"
    return h + BOT


def _bar(step, total, title, detail=""):
    filled = round(step * 14 / max(total, 1))
    bar = "▓" * filled + "░" * (14 - filled)
    txt = (f"{_hdr('در حال اجرا...')}\n\n{bar} <b>"
           f"{round(step * 100 / max(total, 1))}%</b>\n"
           f"📍 {step}/{total}\n\n{MID}\n{title}")
    if detail:
        txt += f"\n{detail}"
    return txt


def _rows(panels):
    out = ""
    for p in panels:
        ic = ICONS.get(p.get("status", ""), "⏳")
        out += f"\n{ic} <b>{p['name']}</b>"
        if p.get("url"):
            out += f"\n     🌐 {p['url'].replace('https://', '')}/managepanel/"
    return out



class Wizard:
    def __init__(self, api: Railway):
        self.api = api
        self.state = "idle"
        self.panels = []          # [{name, sid, url, status}]
        self.project_id = ""
        self.env_id = ""
        self.links = []           # [(panel, vless_url)]
        self.error = ""
        self.errors = []          # per-panel error details

    # ── stage 1: deploy panels + inbounds ──
    async def deploy(self, status_cb) -> bool:
        """status_cb(text) is awaited for live progress. Returns success."""
        self.state = "deploying"
        total = len(config.PANELS) + 2

        ws_id, email = await asyncio.to_thread(self.api.whoami)
        await status_cb(_bar(0, total, f"👤 اکانت: <code>{email}</code>"))

        proj = await asyncio.to_thread(self.api.create_project,
                                       config.PROJECT_PREFIX, ws_id)
        self.project_id = proj["id"]
        self.env_id = await asyncio.to_thread(self.api.first_env, self.project_id)
        await status_cb(_bar(1, total, f"📦 پروژه ساخته شد: <code>{proj['name']}</code>"))

        sem = asyncio.Semaphore(4)

        async def make(p):
            async with sem:
                try:
                    s = await asyncio.to_thread(self.api.create_service, p, self.project_id)
                except AppError as e:
                    self.errors.append(f"{p}: {e.user_msg[:80]}")
                    log.warning("create %s: %s", p, e)
                    return
                # service EXISTS now — always track it, whatever happens next
                entry = {"name": p, "sid": s["id"], "url": "", "status": "WAITING"}
                self.panels.append(entry)
                try:
                    await asyncio.to_thread(self.api.deploy, s["id"], self.env_id)
                except LimitError as e:
                    self.errors.append(f"{p} deploy: {e.user_msg[:60]}")
                    entry["status"] = "LIMIT"
                    return
                except AppError as e:
                    self.errors.append(f"{p} deploy: {e.user_msg[:60]}")
                try:
                    dom = await asyncio.to_thread(self.api.create_domain,
                                                  s["id"], self.env_id,
                                                  config.DOMAIN_PORT)
                    if dom:
                        entry["url"] = f"https://{dom}"
                except AppError as e:
                    log.warning("domain %s: %s", p, e)

        await asyncio.gather(*(make(n) for n in config.PANELS))
        if not self.panels:
            reason = "; ".join(self.errors[:3]) or "دلیل نامشخص"
            self.fail(f"هیچ سرویسی ساخته نشد.\n🔍 {reason}")
            return False

        # poll deployments
        end = time.time() + config.POLL_MAX
        pending = list(self.panels)
        while pending and time.time() < end:
            await asyncio.sleep(config.POLL_EVERY)
            still = []
            for p in pending:
                d = await asyncio.to_thread(self.api.last_deployment, p["sid"])
                st = (d or {}).get("status") or "WAITING"
                p["status"] = st
                if st == "SUCCESS":
                    if not p["url"] and d.get("staticUrl"):
                        p["url"] = f"https://{d['staticUrl']}"
                elif st in ("FAILED", "CRASHED", "REMOVED"):
                    pass
                else:
                    still.append(p)
            done = len([p for p in self.panels if p.get("status") not in ("WAITING", "DEPLOYING", "BUILDING")])
            await status_cb(_bar(2, total,
                            f"📡 SUCCESS {done}/{len(self.panels)}",
                            _rows(self.panels)))
            pending = still

        # create inbounds (4 per panel) — wait for each panel's web UI first
        await status_cb(_bar(2, total,
                             f"🔌 ساخت {config.IN_PER_PANEL} اینباند برای هر پنل..."))
        ib_lines = []
        from xui import wait_ready
        for p in self.panels:
            if p["status"] != "SUCCESS" or not p["url"]:
                continue
            await status_cb(f"{_hdr('اینباندها 🔌')}\n{MID}\n"
                            + "\n".join(ib_lines)
                            + f"\n\n⏳ منتظر آماده شدن {p['name']}...")
            await asyncio.to_thread(wait_ready, p["url"], timeout=120)
            try:
                made = await asyncio.to_thread(
                    _make_inbounds, p["url"], p["name"])
                ib_lines.append(f"✅ <b>{p['name']}</b> ← {made}/{config.IN_PER_PANEL}"
                                if made else
                                f"⚠️ <b>{p['name']}</b> ← ساخته نشد، دوباره از بخش پروتکل‌ها امتحان کن")
            except PanelError as e:
                ib_lines.append(f"⚠️ <b>{p['name']}</b> → {e.user_msg[:50]}")
        await status_cb(
            f"{_hdr('اینباندها ✅')}\n{MID}\n" + "\n".join(ib_lines))

        # ── stage 2: pause ──
        self.state = "paused"
        return True

    def fail(self, msg):
        self.state = "idle"
        self.error = msg

    # ── stage 3: domains ──
    async def set_domains(self, status_cb) -> int:
        self.state = "domains"
        ok = 0
        sem = asyncio.Semaphore(4)

        async def one(p):
            nonlocal ok
            async with sem:
                try:
                    dom = await asyncio.to_thread(
                        self.api.create_domain, p["sid"], self.env_id,
                        config.DOMAIN_PORT)
                    if dom:
                        ok += 1
                        p["url"] = f"https://{dom}"
                        p["status"] = "SUCCESS"
                except AppError:
                    pass

        await asyncio.gather(*(one(p) for p in self.panels))
        self.state = "idle"
        return ok

    # ── stage 4: nodes ──
    async def link_nodes(self, status_cb) -> list[str]:
        self.state = "nodes"
        main = next((p for p in self.panels
                     if p["name"] == config.MAIN_PANEL and p.get("url")), None)
        others = [p for p in self.panels
                  if p.get("url") and p["name"] != config.MAIN_PANEL]
        lines = []
        if not main:
            return [f"❌ پنل اصلی <b>{config.MAIN_PANEL}</b> پیدا نشد."]

        for p in others:
            try:
                def work():
                    mp = Panel(main["url"])
                    if not mp.login():
                        raise PanelError("ورود به پنل اصلی ناموفق")
                    np = Panel(p["url"])
                    if not np.login():
                        raise PanelError(f"ورود به {p['name']} ناموفق")
                    res = mp.add_node(p["name"], p["url"],
                                      np.node_uuid(), np.node_token())
                    if not res.get("success"):
                        raise PanelError(res.get("msg", "ناموفق"))
                await asyncio.to_thread(work)
                lines.append(f"✅ <b>{p['name']}</b> → متصل شد")
            except PanelError as e:
                lines.append(f"⚠️ <b>{p['name']}</b> → {e.user_msg[:50]}")
            await status_cb(f"{_hdr('اتصال نودها 🔗')}\n{MID}\n"
                            + "\n".join(lines))
        self.state = "idle"
        return lines


# ── helpers used by wizard ──
def _make_inbounds(url, name):
    """Xray allows ONE inbound per port. So we create ONE ws+tls inbound and add
    IN_PER_PANEL clients inside it — each client gets its own vless link."""
    c = Panel(url)
    if not c.login():
        raise PanelError(f"ورود به {name} ناموفق")

    ib = None
    for candidate in c.inbounds():
        if int(candidate.get("port") or 0) == config.IN_PORT:
            ib = candidate          # reuse existing inbound on our port
            break
    if not ib:
        remark = f"WS-TLS-{name.lower()}-main"  # matches xui.create_ws_tls_inbound
        r = c.create_ws_tls_inbound(
            uuid=str(uuid.uuid4()), email=f"{name.lower()}-main",
            domain=url.replace("https://", ""),
            port=config.IN_PORT, path=config.IN_PATH)
        if not r.get("success"):
            raise PanelError(r.get("msg", "ساخت اینباند ناموفق"))
        for candidate in c.inbounds():
            if candidate.get("remark") == remark:
                ib = candidate
                break

    added = 0
    import json as _json
    raw = ib.get("settings")
    settings = raw if isinstance(raw, dict) else _json.loads(raw or "{}")
    clients = settings.setdefault("clients", [])
    have = {cl.get("email") for cl in clients}
    for k in range(config.IN_PER_PANEL):
        email = f"{name.lower()}-u{k+1}"
        if email in have:
            added += 1
            continue
        clients.append({"id": str(uuid.uuid4()), "flow": "", "email": email,
                        "limitIp": 0, "totalGB": 0, "expiredTime": 0,
                        "enable": True, "tgId": 0, "subId": ""})
        added += 1
    settings["clients"] = clients
    c._call("POST", "/panel/api/inbounds/update/" + str(ib["id"]),
            {**ib, "settings": _json.dumps(settings), "up": 0, "down": 0,
             "total": 0, "expiryTime": 0})
    return added


def wait_ready(url, timeout=90, every=5):
    probe = url.rstrip("/") + "/managepanel/"
    end = time.time() + timeout
    while time.time() < end:
        try:
            if requests.get(probe, timeout=10).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(every)
    return False
