"""
Busca gasto Google Ads da conta IMR.
Saída: data/google_ads_spend.json

Primeira execução: abre navegador pra autorizar (OAuth).
Execuções seguintes: usa o refresh_token salvo em .google_ads_refresh_token.
"""

import json, os, requests, webbrowser, secrets, urllib.parse, http.server, socketserver, threading, time
from pathlib import Path
from datetime import date
from collections import defaultdict

def _load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists(): return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_env()

# ── Credenciais ──────────────────────────────────────────────────────────────
DEVELOPER_TOKEN   = os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"]
CLIENT_ID         = os.environ["GOOGLE_ADS_CLIENT_ID"]
CLIENT_SECRET     = os.environ["GOOGLE_ADS_CLIENT_SECRET"]
CUSTOMER_ID       = os.environ["GOOGLE_ADS_CUSTOMER_ID"]
LOGIN_CUSTOMER_ID = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or None

# ── Período ──────────────────────────────────────────────────────────────────
SINCE = "2026-04-01"
UNTIL = date.today().isoformat()

def week_of(date_str):
    """Bucket w1-w4 por dia do mês — alinhado com a lógica do dashboard."""
    if not date_str: return "w4"
    day = int(date_str[8:10])
    if day <= 7:  return "w1"
    if day <= 14: return "w2"
    if day <= 21: return "w3"
    return "w4"

def month_of(date_str):
    """Retorna 'YYYY-MM' a partir de 'YYYY-MM-DD'."""
    return date_str[:7] if date_str else "2026-04"

# ── OAuth ────────────────────────────────────────────────────────────────────
SCOPE = "https://www.googleapis.com/auth/adwords"
REFRESH_TOKEN_PATH = Path(__file__).resolve().parent / ".google_ads_refresh_token"

def oauth_flow():
    """Abre navegador, captura code, troca por refresh_token e salva."""
    port = 8765
    redirect_uri = f"http://localhost:{port}"
    state = secrets.token_urlsafe(16)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })

    captured = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("state", [""])[0] != state:
                self.send_response(400); self.end_headers()
                self.wfile.write(b"State mismatch"); return
            if "code" in qs:
                captured["code"] = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8"); self.end_headers()
                self.wfile.write("<h2>Autorizado! Pode fechar esta aba.</h2>".encode("utf-8"))
            elif "error" in qs:
                captured["error"] = qs["error"][0]
                self.send_response(400); self.end_headers()
                self.wfile.write(f"Erro: {qs['error'][0]}".encode("utf-8"))
        def log_message(self, *a): pass

    server = socketserver.TCPServer(("localhost", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"\nAbrindo navegador para autorização...")
    print(f"Se não abrir automaticamente:\n{auth_url}\n")
    webbrowser.open(auth_url)

    timeout = time.time() + 300
    while "code" not in captured and "error" not in captured and time.time() < timeout:
        time.sleep(0.2)
    server.shutdown()

    if "error" in captured:
        raise RuntimeError(f"OAuth falhou: {captured['error']}")
    if "code" not in captured:
        raise TimeoutError("Timeout esperando autorização")

    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": captured["code"],
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    r.raise_for_status()
    refresh_token = r.json()["refresh_token"]
    REFRESH_TOKEN_PATH.write_text(refresh_token)
    print(f"✅ Refresh token salvo em: {REFRESH_TOKEN_PATH}")
    return refresh_token

def get_access_token(refresh_token):
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    r.raise_for_status()
    return r.json()["access_token"]

# ── Google Ads API ──────────────────────────────────────────────────────────
def google_ads_search(access_token, query):
    url = f"https://googleads.googleapis.com/v21/customers/{CUSTOMER_ID}/googleAds:searchStream"
    headers = {
        "Authorization":    f"Bearer {access_token}",
        "developer-token":  DEVELOPER_TOKEN,
        "Content-Type":     "application/json",
    }
    if LOGIN_CUSTOMER_ID:
        headers["login-customer-id"] = LOGIN_CUSTOMER_ID
    r = requests.post(url, headers=headers, json={"query": query})
    if not r.ok:
        raise RuntimeError(f"API error {r.status_code}: {r.text}")
    return r.json()

def main():
    print("=== Google Ads Spend Fetch ===")

    if REFRESH_TOKEN_PATH.exists():
        refresh_token = REFRESH_TOKEN_PATH.read_text().strip()
        print(f"Usando refresh_token salvo.")
    else:
        print("Primeira execução — abrindo OAuth...")
        refresh_token = oauth_flow()

    access_token = get_access_token(refresh_token)
    print("Access token OK.\n")

    query = f"""
        SELECT
            campaign.name,
            ad_group.name,
            segments.date,
            metrics.cost_micros,
            metrics.impressions,
            metrics.clicks
        FROM ad_group
        WHERE segments.date BETWEEN '{SINCE}' AND '{UNTIL}'
    """

    print("Consultando ad_groups...")
    chunks = google_ads_search(access_token, query)

    campaign_spend = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    adgroup_spend  = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    for chunk in chunks:
        for row in chunk.get("results", []):
            camp_name = row.get("campaign", {}).get("name", "—")
            ag_name   = row.get("adGroup",  {}).get("name", "—")
            date_str  = row.get("segments", {}).get("date", "")
            cost      = int(row.get("metrics", {}).get("costMicros", 0)) / 1_000_000
            month     = month_of(date_str)
            week      = week_of(date_str)
            campaign_spend[camp_name][month][week] += cost
            adgroup_spend[ag_name][month][week]    += cost

    total = sum(s for camps in campaign_spend.values() for wks in camps.values() for s in wks.values())
    print(f"  {len(campaign_spend)} campanhas | {len(adgroup_spend)} ad groups")
    print(f"  Gasto total: R${total:,.2f}")
    for name, months in campaign_spend.items():
        camp_total = sum(s for wks in months.values() for s in wks.values())
        print(f"    {name[:55]} → R${camp_total:.2f}")

    def _unwrap(d):
        return {k: {m: dict(wks) for m, wks in months.items()} for k, months in d.items()}

    out = {
        "fetched_at": date.today().isoformat(),
        "period":     {"since": SINCE, "until": UNTIL},
        "campaign":   _unwrap(campaign_spend),
        "adgroup":    _unwrap(adgroup_spend),
    }

    out_path = Path(__file__).resolve().parent / "data/google_ads_spend.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✅ Salvo em: {out_path}")

if __name__ == "__main__":
    main()
