"""
TCP Proxy engine — rotate Railway TCP proxies onto "good" domains.
Sync; translated errors.
"""
import json
import time
import urllib.request

from errors import AppError

URL = "https://api.railway.app/graphql/v2"
UA = {"User-Agent": "railway-cli/5.30.4", "Accept": "*/*"}

DEFAULT_GOOD_DOMAINS = (
    "monorail,nozomi,turntable,trolley,reseau,autorack,metro,hopper,"
    "kodama,interchange,switchyard,junction"
)


def normalize_domains(raw: str) -> set:
    out = set()
    for d in (raw or "").split(","):
        d = d.strip().rstrip(".")
        if not d:
            continue
        if not d.endswith(".proxy.rlwy.net"):
            d += ".proxy.rlwy.net"
        out.add(d)
    return out


class TCPProxy:
    def __init__(self, token: str):
        self.token = token

    def gql(self, query, variables=None):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(URL, data=body, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json", **UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode())
        except Exception as e:
            raise AppError(f"خطای Railway: {e}") from e
        if "data" not in resp:
            raise AppError("Railway: " + json.dumps(resp)[:150])
        return resp["data"]

    # ── CRUD ──
    def list(self, sid, env_id):
        return self.gql("""query($e:String!,$s:String!){tcpProxies(environmentId:$e,
            serviceId:$s){id domain proxyPort applicationPort syncStatus}}""",
            {"e": env_id, "s": sid}).get("tcpProxies") or []

    def create(self, sid, env_id, port):
        return self.gql("""mutation($i:TCPProxyCreateInput!){
            tcpProxyCreate(input:$i){id domain proxyPort syncStatus}}""",
            {"i": {"applicationPort": port, "environmentId": env_id,
                   "serviceId": sid}}).get("tcpProxyCreate") or {}

    def delete(self, proxy_id):
        return bool(self.gql("mutation($id:String!){tcpProxyDelete(id:$id)}",
                             {"id": proxy_id}).get("tcpProxyDelete"))

    # ── helpers ──
    @staticmethod
    def reachable(domain, port, timeout=5):
        import socket
        try:
            s = socket.create_connection((domain, port), timeout=timeout)
            s.close()
            return True
        except Exception:
            return False

    def wait_active(self, sid, env_id, timeout=240):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            live = [p for p in self.list(sid, env_id)
                    if p.get("syncStatus") == "ACTIVE"]
            if live:
                last = live[0]
                if len(live) == 1:
                    return live[0]
            time.sleep(5)
        return last

    # ── rotation ──
    def rotate(self, sid, env_id, port, targets=None, max_tries=30,
               cooldown=8, on_progress=None, cancel=None):
        """Rotate until a target domain is hit (targets=None → first reachable)."""
        targets = targets or set()

        def log(m):
            if on_progress: on_progress(m)

        for attempt in range(1, max_tries + 1):
            if cancel and cancel():
                log("⏹ متوقف شد"); return None

            for p in self.list(sid, env_id):
                if (p.get("domain") not in targets
                        and p.get("syncStatus") not in ("DELETED", "DELETING")):
                    log(f"[{attempt}] 🗑 {p['domain']}:{p.get('proxyPort')}")
                    try: self.delete(p["id"])
                    except Exception as e: log(f"[{attempt}] حذف ناموفق: {e}")
            time.sleep(max(cooldown - 2, 3))

            try:
                c = self.create(sid, env_id, port)
            except Exception as e:
                log(f"[{attempt}] ساخت ناموفق: {e}"); time.sleep(cooldown); continue
            if not c:
                log(f"[{attempt}] ساخت ناموفق"); time.sleep(cooldown); continue

            dom = (c.get("domain") or "?").rstrip(".")
            log(f"[{attempt}] ✨ → {dom}")

            proxy = self.wait_active(sid, env_id)
            final = ((proxy or {}).get("domain") or "").rstrip(".")
            if final and final != dom:
                dom = final; log(f"[{attempt}] نهایی → {dom}")
            prt = (proxy or c).get("proxyPort") or port

            hit = (dom in targets) if targets else self.reachable(dom, prt)
            if not targets:
                log(f"[{attempt}] تست {dom}:{prt} → {'✓' if hit else '✗'}")
            if hit:
                log(f"🎯 HIT → {dom}:{prt}")
                return (dom, prt)
            time.sleep(cooldown)

        log(f"❌ بعد از {max_tries} تلاش به هدف نرسید")
        return None
