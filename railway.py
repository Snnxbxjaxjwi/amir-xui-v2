"""
Railway GraphQL — sync core, translated errors, retry on 30s rate limit.
"""
import time

import requests

import config
from errors import AuthError, LimitError, NetworkError, AppError

URL = "https://backboard.railway.com/graphql/v2"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "railway-cli/5.30.4",   # avoids masked 400 responses
    "Accept": "*/*",
}


class Railway:
    def __init__(self, token: str):
        self.h = {"Authorization": f"Bearer {token}", **HEADERS}

    def gql(self, query: str, variables: dict | None = None) -> dict:
        try:
            r = requests.post(URL, json={"query": query, "variables": variables or {}},
                              headers=self.h, timeout=30)
        except requests.RequestException as e:
            raise NetworkError(f"خطای شبکه: {e}") from e

        if r.status_code == 401:
            raise AuthError
        if r.status_code == 400:
            # masked error on mutations → rate limit / quota; caller may retry once
            raise LimitError
        data = r.json()
        if data.get("errors"):
            msg = "; ".join(e.get("message", "?") for e in data["errors"])
            low = msg.lower()
            if "limit exceeded" in low or "problem processing" in low:
                raise LimitError
            if "not authorized" in low:
                raise AuthError
            raise AppError(f"Railway: {msg[:180]}")
        return data.get("data", {})

    def gql_retry(self, query, variables=None):
        """Run gql; on LimitError wait out the 30s project-rate-limit and retry once."""
        try:
            return self.gql(query, variables)
        except LimitError:
            time.sleep(config.RATE_LIMIT_WAIT)
            return self.gql(query, variables)

    # ── queries ──
    def whoami(self) -> tuple[str, str]:
        d = self.gql("{me{email workspaces{id}}}")
        me = d.get("me") or {}
        ws = (me.get("workspaces") or [{}])[0].get("id", "")
        return ws, me.get("email", "")

    def projects(self) -> list[dict]:
        d = self.gql("{me{workspaces{projects(first:50){edges{node{id name createdAt}}}}}}")
        out = []
        for w in (d.get("me") or {}).get("workspaces", []):
            out += [e["node"] for e in (w.get("projects") or {}).get("edges", [])]
        return sorted(out, key=lambda x: x.get("createdAt", ""), reverse=True)

    def environments(self, pid: str) -> list[dict]:
        d = self.gql("query($p:String!){environments(projectId:$p){edges{node{id name}}}}",
                     {"p": pid})
        return [e["node"] for e in ((d.get("environments") or {}).get("edges") or [])]

    def first_env(self, pid: str) -> str:
        envs = self.environments(pid)
        return envs[0]["id"] if envs else ""

    # ── mutations ──
    def create_project(self, name, ws_id):
        d = self.gql_retry("""mutation($i:ProjectCreateInput!){projectCreate(input:$i){id name}}""",
                           {"i": {"name": name, "workspaceId": ws_id}})
        p = d.get("projectCreate") or {}
        if not p.get("id"):
            raise AppError("ساخت پروژه ناموفق بود.")
        return p

    def delete_project(self, pid) -> bool:
        return bool(self.gql_retry("mutation($id:String!){projectDelete(id:$id)}",
                                   {"id": pid}).get("projectDelete"))

    def create_service(self, name, pid):
        d = self.gql("""mutation($i:ServiceCreateInput!){serviceCreate(input:$i){id name}}""",
                     {"i": {"projectId": pid, "name": name,
                            "source": {"image": config.IMAGE}}})
        s = d.get("serviceCreate") or {}
        if not s.get("id"):
            raise AppError(f"ساخت سرویس {name} ناموفق.")
        return s

    def deploy(self, sid, env_id):
        self.gql("""mutation($s:String!,$e:String!){
            serviceInstanceDeploy(serviceId:$s,environmentId:$e)}""",
            {"s": sid, "environmentId": env_id})

    def set_region(self, sid, env_id, region):
        """Place the service in a Railway region (available: sfo, iad, sin, pdx, ams).
        Call BEFORE the first deploy so the build lands in the right region.
        NOTE: on some plans Railway returns true but silently drops the write —
        always confirm with get_region()."""
        self.gql("""mutation($s:String!,$e:String!,$r:String!){
            serviceInstanceUpdate(serviceId:$s,environmentId:$e,
                                  input:{region:$r})}""",
            {"s": sid, "e": env_id, "r": region})

    def get_region(self, sid, env_id) -> str | None:
        """Read back the instance region (None = not set / write was ignored)."""
        d = self.gql("""query($id:String!,$e:String!){
            serviceInstance(serviceId:$id,environmentId:$e){region}}""",
            {"id": sid, "e": env_id})
        return ((d.get("serviceInstance") or {}).get("region"))

    def create_domain(self, sid, env_id, port):
        d = self.gql("""mutation($i:ServiceDomainCreateInput!){
            serviceDomainCreate(input:$i){domain}}""",
            {"i": {"serviceId": sid, "environmentId": env_id,
                   "targetPort": port}})
        return (d.get("serviceDomainCreate") or {}).get("domain", "")

    def last_deployment(self, sid):
        d = self.gql("""query($id:String!){service(id:$id){
            deployments(last:1){edges{node{status staticUrl}}}}}""", {"id": sid})
        edges = ((d.get("service") or {}).get("deployments") or {}).get("edges") or []
        return edges[-1]["node"] if edges else None
