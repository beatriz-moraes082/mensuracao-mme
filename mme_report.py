#!/usr/bin/env python3
"""IMR (Ipioca Mar Resort / MME Vacation Club) — relatório semanal/mensal automatizado.

Cadência (padrão dos 15 outros relatórios):
    1ª segunda → MENSAL (mês anterior inteiro)
    2ª segunda → SEMANAL (1 a 7 do mês atual)
    3ª segunda → SEMANAL (1 a 15 do mês atual)
    4ª/última  → SEMANAL (últimos 7 dias)

Coleta:
    Meta Ads (act_2352574621900370) — gasto, leads, métricas; separa Fundo vs Topo
    Google Ads (customer 2416269127, MCC 1474296260) — gasto + conversões (inclui PMax)
    Kommo CRM (ipiocamarresort) — funil SDR/Closer/Duque, vendas, perdas, corretores

Atualiza:
    description da task de Relatório (Ipioca Mar Resort, 86ahp619r)
    comentário em Otimizações (MME Vacation Club, 86ahhq9rk) — análise estratégica

Uso:
    python3 mme_report.py                 # dry-run, modo automático pela data
    python3 mme_report.py --apply         # aplica
    python3 mme_report.py --force-mode mensal --date 2026-05-04 --apply
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

BRT = timezone(timedelta(hours=-3))

META_API = "v21.0"
META_TOKEN = os.environ["META_TOKEN"]
META_AD_ACCOUNT = os.environ.get("META_ACCOUNT", "act_2352574621900370")

CLICKUP_TOKEN = os.environ["CLICKUP_TOKEN"]
TASK_RELATORIO   = os.environ.get("MME_TASK_RELATORIO",   "86ahp619r")  # Ipioca Mar Resort — lista 📊 Relatórios
TASK_OTIMIZACOES = os.environ.get("MME_TASK_OTIMIZACOES", "86ahhq9rk")  # MME Vacation Club — lista 📈 Otimizações
# Alias retrocompat com a estrutura do Maia (build_description usa TASK_SEMANAL/TASK_MENSAL):
TASK_SEMANAL = TASK_RELATORIO
TASK_MENSAL  = TASK_RELATORIO

KOMMO_TOKEN = os.environ["KOMMO_TOKEN"]
KOMMO_SUBDOMAIN = os.environ.get("KOMMO_SUBDOMAIN", "ipiocamarresort")

# ── Google Ads (opcional — se faltar credencial, bloco vira N/D) ─────────────
GADS_DEVELOPER_TOKEN   = os.environ.get("GADS_DEVELOPER_TOKEN")
GADS_CLIENT_ID         = os.environ.get("GADS_CLIENT_ID")
GADS_CLIENT_SECRET     = os.environ.get("GADS_CLIENT_SECRET")
GADS_REFRESH_TOKEN     = os.environ.get("GADS_REFRESH_TOKEN")
GADS_CUSTOMER_ID       = os.environ.get("GADS_CUSTOMER_ID", "2416269127")
GADS_LOGIN_CUSTOMER_ID = os.environ.get("GADS_LOGIN_CUSTOMER_ID", "1474296260")
GADS_AVAILABLE = all([GADS_DEVELOPER_TOKEN, GADS_CLIENT_ID, GADS_CLIENT_SECRET, GADS_REFRESH_TOKEN, GADS_CUSTOMER_ID])

# ── Status do Kommo IMR (3 pipelines: SDR, Closer, Duque) ────────────────────
QUALIFIED_STATUSES = {98147491}                       # Lead qualificado (SDR)
MEETING_STATUSES   = {98162603, 98168239}             # Reunião agendada / realizada
PROPOSAL_STATUSES  = {98169055}                       # Proposta enviada (Closer)
SINAL_VERDE_STATUS = 98334563                         # Sinal Verde (Closer — quase venda)
LOST_STATUS = 143                                     # Venda perdida
WON_STATUS  = 142                                     # Venda ganha

STATUS_NAMES = {
    # SDR
    98147475: "Incoming leads (SDR)", 99055915: "Abordagem inicial", 98618883: "Pré-atendimento",
    98147479: "Lead novo", 98147483: "Follow-up", 98147487: "Qualificação",
    98147491: "Lead qualificado", 98162603: "Reunião agendada",
    # Closer
    98168235: "Incoming leads (Closer)", 98168239: "Reunião realizada",
    98169055: "Proposta enviada", 98169059: "Follow-up (Closer)", 98334563: "Sinal Verde",
    # Duque (nutrição)
    98164999: "Incoming leads (Duque)", 98165003: "Nutrição SDR",
    99170411: "Nutrição BDR", 98524255: "Nutrição Closer",
    # Terminais
    142: "Venda ganha", 143: "Venda perdida",
}
LEAD_ACTION_TYPE = "lead"  # IMR roda Lead Form do Meta


def is_topo_funil(name):
    n = (name or "").lower()
    return ("topo de funil" in n or "tráfego" in n or "trafego" in n
            or "marca" in n or "instagram" in n)


# ── Google Ads ───────────────────────────────────────────────────────────────
def google_ads_access_token():
    data = urllib.parse.urlencode({
        "client_id": GADS_CLIENT_ID,
        "client_secret": GADS_CLIENT_SECRET,
        "refresh_token": GADS_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    r = json.loads(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30).read())
    return r["access_token"]


def google_ads_insights(since, until):
    """Retorna {total: {spend, impressions, clicks, leads, cpl}, campaigns: [{name, spend, leads, cpl, status}]}.
    Query nível campaign (captura Performance Max, que não tem ad_group)."""
    if not GADS_AVAILABLE:
        return {"total": {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}, "campaigns": []}
    access = google_ads_access_token()
    headers = {
        "Authorization": f"Bearer {access}",
        "developer-token": GADS_DEVELOPER_TOKEN,
        "login-customer-id": GADS_LOGIN_CUSTOMER_ID,
        "Content-Type": "application/json",
    }
    url = f"https://googleads.googleapis.com/v21/customers/{GADS_CUSTOMER_ID}/googleAds:search"
    query = (
        "SELECT campaign.name, campaign.status, metrics.cost_micros, metrics.impressions, "
        "metrics.clicks, metrics.conversions "
        f"FROM campaign WHERE segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'"
    )
    body = json.dumps({"query": query}).encode()
    d = json.loads(urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers=headers, method="POST"), timeout=30
    ).read())
    total = {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}
    # Agrupa por campanha (uma query retorna 1 linha por (campanha, período agregado))
    by_camp = defaultdict(lambda: {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0.0, "status": ""})
    for row in d.get("results", []):
        camp_name = (row.get("campaign") or {}).get("name", "—")
        camp_status = (row.get("campaign") or {}).get("status", "")
        m = row.get("metrics") or {}
        spend = int(m.get("costMicros", 0)) / 1_000_000
        impressions = int(m.get("impressions", 0))
        clicks = int(m.get("clicks", 0))
        leads = float(m.get("conversions", 0))
        by_camp[camp_name]["spend"] += spend
        by_camp[camp_name]["impressions"] += impressions
        by_camp[camp_name]["clicks"] += clicks
        by_camp[camp_name]["leads"] += leads
        by_camp[camp_name]["status"] = camp_status
        total["spend"] += spend
        total["impressions"] += impressions
        total["clicks"] += clicks
        total["leads"] += leads
    total["leads"] = int(round(total["leads"]))
    total["cpl"] = total["spend"] / total["leads"] if total["leads"] else 0.0
    campaigns = []
    for name, c in by_camp.items():
        leads_int = int(round(c["leads"]))
        campaigns.append({
            "name": name,
            "spend": c["spend"],
            "impressions": c["impressions"],
            "clicks": c["clicks"],
            "leads": leads_int,
            "cpl": (c["spend"] / leads_int) if leads_int else 0.0,
            "status": c["status"],
        })
    campaigns.sort(key=lambda x: -x["spend"])
    return {"total": total, "campaigns": campaigns}


# ---------------- HTTP ----------------
def _http(method, url, headers=None, data=None, allow_204=False):
    h = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            content = r.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        if e.code == 204 and allow_204:
            return {}
        msg = e.read().decode("utf-8", "replace")[:300] if e.fp else ""
        print(f"HTTP {e.code} on {method} {url}: {msg}", file=sys.stderr)
        raise


# ---------------- Meta ----------------
def meta_get(path, params=None):
    p = dict(params or {})
    p["access_token"] = META_TOKEN
    qs = urllib.parse.urlencode(p)
    return _http("GET", f"https://graph.facebook.com/{META_API}/{path}?{qs}")


def _action_value(actions, action_type):
    for a in actions or []:
        if a.get("action_type") == action_type:
            return int(float(a.get("value", 0)))
    return 0


def meta_campaign_status_map(act_id):
    """Retorna {campaign_id: effective_status} pra account toda."""
    out = {}
    next_url = None
    params = {"fields": "id,effective_status", "limit": 200}
    while True:
        if next_url is None:
            d = meta_get(f"{act_id}/campaigns", params)
        else:
            with urllib.request.urlopen(next_url) as r:
                d = json.loads(r.read())
        for c in d.get("data", []):
            out[c["id"]] = c.get("effective_status", "")
        nxt = (d.get("paging") or {}).get("next")
        if not nxt:
            break
        next_url = nxt
    return out


def varredura_meta(act_id, status_map):
    """Detecta problemas operacionais: sem gasto 24h+ / sem lead 48h+ (apesar de campanha ativa)."""
    alerts = []
    has_active = any((m.get("status") if isinstance(m, dict) else m) == "ACTIVE" for m in (status_map or {}).values())
    if not has_active:
        return alerts
    today = datetime.now(timezone(timedelta(hours=-3))).date()
    try:
        ins24 = meta_insights(act_id, (today - timedelta(days=1)).isoformat(), today.isoformat(), status_map)
        if ins24["total"]["spend"] == 0:
            alerts.append("Conta Meta sem gasto há 24h+ apesar de campanha ativa — verificar saldo, limite de orçamento ou status de pause")
    except Exception as e:
        print(f"  [varredura sem-spend] {e}", file=sys.stderr)
    try:
        ins48 = meta_insights(act_id, (today - timedelta(days=2)).isoformat(), today.isoformat(), status_map)
        if ins48["total"]["leads"] == 0 and ins48["total"]["spend"] > 0:
            alerts.append("Sem lead gerado há 48h+ apesar de gasto ativo — verificar formulário, criativo ou fadiga de público")
    except Exception as e:
        print(f"  [varredura sem-lead] {e}", file=sys.stderr)
    return alerts


def meta_insights(act_id, since, until, status_map=None):
    """Agrega insights do período por campanha."""
    status_map = status_map or {}
    fields = "campaign_id,campaign_name,spend,reach,impressions,clicks,inline_link_clicks,actions"
    params = {
        "fields": fields, "level": "campaign",
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": 200,
    }
    d = meta_get(f"{act_id}/insights", params)
    rows = d.get("data", [])
    total = {"spend": 0.0, "lead_spend": 0.0, "reach": 0, "impressions": 0, "clicks": 0, "leads": 0}
    campaigns = []
    for r in rows:
        cid = r.get("campaign_id")
        actions = r.get("actions") or []
        c = {
            "id": cid, "name": r.get("campaign_name"),
            "spend": float(r.get("spend", 0)),
            "reach": int(r.get("reach", 0)),
            "impressions": int(r.get("impressions", 0)),
            "clicks": int(r.get("inline_link_clicks", r.get("clicks", 0))),
            "leads": _action_value(actions, LEAD_ACTION_TYPE),
            # Topo de funil: link_click proxy pra visitas ao perfil; post = shares; post_save = salvamentos
            "profile_visits": _action_value(actions, "link_click"),
            "shares": _action_value(actions, "post"),
            "saves": _action_value(actions, "onsite_conversion.post_save"),
            "status": status_map.get(cid, ""),
        }
        for k in ("spend", "reach", "impressions", "clicks", "leads"):
            total[k] += c[k]
        if not is_topo_funil(c["name"]):
            total["lead_spend"] += c["spend"]
        campaigns.append(c)
    total["cpl"] = total["lead_spend"] / total["leads"] if total["leads"] else 0.0
    return {"total": total, "campaigns": campaigns}


# ---------------- Kommo ----------------
def kommo_get(path):
    return _http("GET", f"https://{KOMMO_SUBDOMAIN}.kommo.com/api/v4/{path}",
                 headers={"Authorization": f"Bearer {KOMMO_TOKEN}"}, allow_204=True)


def kommo_aggregate(start_ts, end_ts):
    leads = []
    page = 1
    while True:
        d = kommo_get(f"leads?filter[created_at][from]={start_ts}&filter[created_at][to]={end_ts}&with=contacts&limit=250&page={page}")
        batch = (d.get("_embedded") or {}).get("leads", [])
        if not batch:
            break
        leads.extend(batch)
        if len(batch) < 250:
            break
        page += 1

    # contatos vinculados (público + criativo são custom fields do contato)
    contact_ids = set()
    for l in leads:
        for c in (l.get("_embedded") or {}).get("contacts", []):
            contact_ids.add(c["id"])
    contacts_meta = {}
    ids = list(contact_ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        qs = "&".join(f"filter[id][]={x}" for x in chunk)
        d = kommo_get(f"contacts?{qs}&limit=250")
        for c in (d.get("_embedded") or {}).get("contacts", []):
            cf = {f["field_name"]: [v.get("value") for v in f.get("values", [])]
                  for f in (c.get("custom_fields_values") or [])}
            contacts_meta[c["id"]] = cf

    # motivos de perda
    loss_reasons = {}
    try:
        lr = kommo_get("leads/loss_reasons")
        loss_reasons = {l["id"]: l["name"]
                        for l in (lr.get("_embedded") or {}).get("loss_reasons", [])}
    except Exception:
        pass

    # users (corretor_id → nome)
    users = {}
    try:
        u = kommo_get("users?limit=250")
        for usr in (u.get("_embedded") or {}).get("users", []):
            users[usr["id"]] = usr.get("name") or f"user_{usr['id']}"
    except Exception:
        pass

    publicos = defaultdict(Counter)
    criativos = defaultdict(Counter)
    by_emp_status = defaultdict(Counter)   # {empreendimento: {status_id: count}}
    by_corretor = defaultdict(Counter)     # {corretor_id: {status_id: count}}
    daily = Counter()                       # {date_iso: count}
    losses = []
    vendas = []                             # [{id, name, price, corretor_id, closed_at}]
    status_dist = Counter()
    for l in leads:
        sid = l["status_id"]
        status_dist[sid] += 1
        # tags do lead
        tags = [t.get("name", "") for t in (l.get("_embedded") or {}).get("tags", []) or []]
        pub_tags = [t for t in tags if t and not t.lower().startswith("fb")]
        crv_tags = [t for t in tags if t.lower().startswith("fb")]
        pub = pub_tags[0] if pub_tags else None
        crv = crv_tags[0] if crv_tags else None
        publicos[pub or "(sem empreendimento)"][sid] += 1
        criativos[crv or "(sem form)"][sid] += 1
        # funil por empreendimento
        by_emp_status[pub or "(sem empreendimento)"][sid] += 1
        # atividade por corretor (responsible_user_id)
        ruid = l.get("responsible_user_id")
        by_corretor[ruid][sid] += 1
        # ritmo diário
        ts = l.get("created_at")
        if ts:
            d_iso = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=-3))).date().isoformat()
            daily[d_iso] += 1
        if sid == LOST_STATUS:
            losses.append({"id": l["id"], "reason_id": l.get("loss_reason_id"),
                           "name": l.get("name"), "corretor_id": ruid})
        if sid == WON_STATUS:
            vendas.append({
                "id": l["id"], "name": l.get("name") or "(sem nome)",
                "price": float(l.get("price") or 0),
                "corretor_id": ruid, "closed_at": l.get("closed_at"),
            })

    qualified = sum(n for s, n in status_dist.items() if s in QUALIFIED_STATUSES)
    return {
        "total_leads": len(leads),
        "qualified": qualified,
        "lost": len(losses),
        "vendas": vendas,
        "receita": sum(v["price"] for v in vendas),
        "status_dist": dict(status_dist),
        "publicos": {k: dict(v) for k, v in publicos.items()},
        "criativos": {k: dict(v) for k, v in criativos.items()},
        "losses": losses,
        "loss_reasons": loss_reasons,
        "by_emp_status": {k: dict(v) for k, v in by_emp_status.items()},
        "by_corretor": {k: dict(v) for k, v in by_corretor.items()},
        "users": users,
        "daily": dict(daily),
    }


# ---------------- Período ----------------
def br_today():
    return datetime.now(timezone(timedelta(hours=-3))).date()


def effective_today(d):
    if d.weekday() == 0:
        return d
    return d - timedelta(days=d.weekday())


def monday_index(d):
    """Qual segunda do mês é d (1..5)? None se não for segunda."""
    if d.weekday() != 0:
        return None
    return ((d.day - 1) // 7) + 1


def decide_mode(d, force=None):
    if force:
        return force
    idx = monday_index(d)
    if idx == 1:
        return "mensal"
    return "semanal"


def period_label(s, e, mode):
    meses = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    if mode == "mensal":
        return f"{meses[s.month-1]} {s.year}"
    days = (e - s).days + 1
    if s.day == 1 and days == 15:
        return "1ª quinzena do mês"
    if s.day == 1 and days == 7:
        return "Primeiros 7 dias do mês"
    return "Últimos 7 dias"


def compute_periods(today, mode):
    """Retorna ((curr_start, curr_end), (prev_start, prev_end))."""
    if mode == "mensal":
        first_this = today.replace(day=1)
        prev_end = first_this - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        prev_prev_end = prev_start - timedelta(days=1)
        prev_prev_start = prev_prev_end.replace(day=1)
        return (prev_start, prev_end), (prev_prev_start, prev_prev_end)
    idx = monday_index(today)
    if idx == 2:
        s, e = today.replace(day=1), today.replace(day=1) + timedelta(days=6)
    elif idx == 3:
        s, e = today.replace(day=1), today.replace(day=1) + timedelta(days=14)
    else:
        e = today - timedelta(days=1)
        s = e - timedelta(days=6)
    span = (e - s).days
    pe = s - timedelta(days=1)
    ps = pe - timedelta(days=span)
    return (s, e), (ps, pe)


# ---------------- Format ----------------
def br_date(d): return d.strftime("%d/%m/%Y")
def fmt_money(v):
    return ("R$ " + f"{v:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")
def fmt_int(v):
    return f"{int(v):,}".replace(",", ".")


def fmt_dec(v, n=2):
    return f"{v:.{n}f}".replace(".", ",")


def status_emoji(status):
    return "🟢" if status == "ACTIVE" else "⏸️"


def build_description(meta_now, meta_prev, google_now, google_prev, period_now, period_prev, mode, kommo_now=None, kommo_prev=None):
    """Description do IMR: Visão Geral consolidada + Meta + Google + Kommo + Detalhamento por campanha."""
    s_now, e_now = period_now
    s_prev, e_prev = period_prev
    mt, mp = meta_now["total"], meta_prev["total"]
    gt = (google_now or {}).get("total") or {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}
    gp = (google_prev or {}).get("total") or {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}

    # Visão Geral consolidada (Meta + Google)
    total_invest_now  = mt["spend"] + gt["spend"]
    total_invest_prev = mp["spend"] + gp["spend"]
    total_leads_now   = mt["leads"] + gt["leads"]
    total_leads_prev  = mp["leads"] + gp["leads"]
    # CPL médio = lead_spend (Meta fundo + Google total) / leads totais
    lead_spend_now  = mt.get("lead_spend", mt["spend"]) + gt["spend"]
    lead_spend_prev = mp.get("lead_spend", mp["spend"]) + gp["spend"]
    cpl_medio_now  = lead_spend_now  / total_leads_now  if total_leads_now  else 0.0
    cpl_medio_prev = lead_spend_prev / total_leads_prev if total_leads_prev else 0.0

    def _delta_str(n, p, is_money=False, lower_is_better=False):
        if not p:
            return f"(vs {fmt_money(p) if is_money else p})"
        d = n - p
        pct = (d / p * 100) if p else 0
        sign = "+" if d >= 0 else ""
        d_str = f"{sign}{fmt_money(d)}" if is_money else f"{sign}{d}"
        return f"({fmt_money(p) if is_money else p} → {fmt_money(n) if is_money else n}, {d_str} / {sign}{pct:.1f}%)"

    lines = [
        "📊 RESULTADOS DAS CAMPANHAS — Ipioca Mar Resort",
        f"Período analisado: {period_label(s_now, e_now, mode)} → {br_date(s_now)} a {br_date(e_now)}",
        "",
        "🎯 VISÃO GERAL (Meta + Google)",
        f"Investimento total: {fmt_money(total_invest_now)}",
        f"Leads gerados: {total_leads_now}",
        f"CPL médio: {fmt_money(cpl_medio_now)} *",
        "",
    ]

    if total_leads_prev or total_invest_prev:
        comp_label = "vs período anterior" if mode == "mensal" else "vs semana anterior"
        lines += [
            f"📈 Comparativo {comp_label} ({br_date(s_prev)} a {br_date(e_prev)}):",
            f"Leads: {_delta_str(total_leads_now, total_leads_prev)}",
            f"CPL: {_delta_str(cpl_medio_now, cpl_medio_prev, is_money=True, lower_is_better=True)}",
            f"Investimento: {_delta_str(total_invest_now, total_invest_prev, is_money=True)}",
            "",
        ]

    # ── Meta Ads ─────────────────────────────────────────────────────────────
    lines += ["──────────────────────────────", f"🔵 META ADS — {fmt_money(mt['spend'])}", ""]
    # Fundo de funil agregado (exclui topo)
    fundo_camps = [c for c in meta_now["campaigns"] if not is_topo_funil(c["name"])]
    fundo_spend = sum(c["spend"] for c in fundo_camps)
    fundo_leads = sum(c["leads"] for c in fundo_camps)
    fundo_reach = sum(c["reach"] for c in fundo_camps)
    fundo_impr  = sum(c["impressions"] for c in fundo_camps)
    fundo_clk   = sum(c["clicks"] for c in fundo_camps)
    fundo_cpl   = fundo_spend / fundo_leads if fundo_leads else 0
    if fundo_camps:
        lines += [
            "Campanha de Leads (Fundo de Funil)",
            f"Alcance: {fmt_int(fundo_reach)}  ·  Impressões: {fmt_int(fundo_impr)}  ·  Cliques: {fmt_int(fundo_clk)}",
            f"Leads: {fundo_leads}  ·  CPL: {fmt_money(fundo_cpl)}",
            "",
        ]
        # Comparativo só do fundo
        fundo_prev_camps = [c for c in meta_prev["campaigns"] if not is_topo_funil(c["name"])]
        f_p_spend = sum(c["spend"] for c in fundo_prev_camps)
        f_p_leads = sum(c["leads"] for c in fundo_prev_camps)
        f_p_cpl   = f_p_spend / f_p_leads if f_p_leads else 0
        if f_p_leads or f_p_spend:
            lines += [
                "vs semana anterior:",
                f"Leads: {_delta_str(fundo_leads, f_p_leads)}",
                f"CPL: {_delta_str(fundo_cpl, f_p_cpl, is_money=True, lower_is_better=True)}",
                "",
            ]
    # Topo de funil agregado
    topo_camps = [c for c in meta_now["campaigns"] if is_topo_funil(c["name"])]
    topo_spend  = sum(c["spend"] for c in topo_camps)
    topo_visits = sum(c.get("profile_visits", 0) for c in topo_camps)
    topo_shares = sum(c.get("shares", 0) for c in topo_camps)
    topo_saves  = sum(c.get("saves", 0) for c in topo_camps)
    if topo_camps:
        lines += [
            "Campanha de Marca (Topo de Funil)",
            f"Investido: {fmt_money(topo_spend)}",
            f"Visitas ao perfil: {fmt_int(topo_visits)}  ·  Compartilhamentos: {fmt_int(topo_shares)}  ·  Salvamentos: {fmt_int(topo_saves)}",
            "",
        ]

    # ── Google Ads ──────────────────────────────────────────────────────────
    if gt["spend"] > 0 or gt["leads"] > 0:
        lines += ["──────────────────────────────", f"🟢 GOOGLE ADS — {fmt_money(gt['spend'])}", ""]
        for c in (google_now or {}).get("campaigns", []):
            lines.append(f"{status_emoji(c.get('status',''))} {c['name']}")
            lines.append(f"Impressões: {fmt_int(c['impressions'])}  ·  Cliques: {fmt_int(c['clicks'])}")
            lines.append(f"Leads: {c['leads']}  ·  CPL: {fmt_money(c['cpl'])}")
            lines.append("")
        # Comparativo
        if gp["leads"] or gp["spend"]:
            lines += [
                "vs semana anterior:",
                f"Leads: {_delta_str(gt['leads'], gp['leads'])}",
                f"CPL: {_delta_str(gt['cpl'], gp['cpl'], is_money=True, lower_is_better=True)}",
                "",
            ]

    # ── Funil Kommo ─────────────────────────────────────────────────────────
    if kommo_now and kommo_now.get("status_dist"):
        def _count(sd, ids):
            return sum(n for sid, n in sd.items() if sid in ids)
        sd = kommo_now["status_dist"]
        sd_prev = (kommo_prev or {}).get("status_dist", {}) if kommo_prev else {}

        rows = [
            ("Entrada (SDR)",       _count(sd, {98147475}),                _count(sd_prev, {98147475})),
            ("Lead qualificado",    _count(sd, QUALIFIED_STATUSES),        _count(sd_prev, QUALIFIED_STATUSES)),
            ("Reunião agendada",    _count(sd, {98162603}),                _count(sd_prev, {98162603})),
            ("Reunião realizada",   _count(sd, {98168239}),                _count(sd_prev, {98168239})),
            ("Proposta enviada",    _count(sd, PROPOSAL_STATUSES),         _count(sd_prev, PROPOSAL_STATUSES)),
            ("Vendas fechadas",     _count(sd, {WON_STATUS}),              _count(sd_prev, {WON_STATUS})),
        ]
        def _delta_k(n, p):
            if not kommo_prev: return ""
            d = n - p
            if d == 0 and p == 0: return f" (vs 0)"
            if p == 0: return f" (vs 0 / +{n})"
            pct = (d / p * 100)
            sign = "+" if d >= 0 else ""
            return f" (vs {p} / {sign}{d} / {sign}{pct:.0f}%)"
        lines += ["──────────────────────────────", "📋 FUNIL COMERCIAL (Kommo)", ""]
        for label, n, p in rows:
            lines.append(f"{label}: {n}{_delta_k(n, p)}")
        lines.append("")

        # Vendas detalhadas (se houver)
        vendas = kommo_now.get("vendas") or []
        if vendas:
            users = kommo_now.get("users") or {}
            receita = kommo_now.get("receita") or 0
            lines += [f"💰 Vendas no período: {len(vendas)} — {fmt_money(receita)} faturado"]
            for v in vendas[:5]:
                corr = users.get(v["corretor_id"], "(sem corretor)") if v["corretor_id"] else "(sem corretor)"
                preco_str = f" — {fmt_money(v['price'])}" if v.get("price") else ""
                lines.append(f"• {v['name']}{preco_str} (corretor {corr})")
            lines.append("")

        # Top 3 motivos de perda
        loss_reasons_map = kommo_now.get("loss_reasons") or {}
        loss_reason_counter = Counter()
        for l in (kommo_now.get("losses") or []):
            rid = l.get("reason_id")
            if rid:
                loss_reason_counter[rid] += 1
        if loss_reason_counter:
            lines.append("Top motivos de perda:")
            for rid, n in loss_reason_counter.most_common(3):
                name = loss_reasons_map.get(rid, f"motivo #{rid}")
                lines.append(f"• {name}: {n}")
            lines.append("")

        # Corretor mais ativo (por número de leads movimentados, exclui terminais)
        by_corr = kommo_now.get("by_corretor") or {}
        users = kommo_now.get("users") or {}
        if by_corr:
            corr_rank = []
            for ruid, dist in by_corr.items():
                ativo = sum(n for sid, n in dist.items() if sid not in (LOST_STATUS, WON_STATUS))
                corr_rank.append((ruid, ativo))
            corr_rank.sort(key=lambda x: -x[1])
            top = corr_rank[0]
            if top[1] > 0:
                nome = users.get(top[0], f"User {top[0]}") if top[0] else "(sem responsável)"
                lines.append(f"Corretor mais ativo: {nome} ({top[1]} leads movimentados)")
                lines.append("")

    # ── Detalhamento por campanha (Meta + Google) ──────────────────────────
    lines += ["──────────────────────────────", "📑 DETALHAMENTO POR CAMPANHA", ""]
    for c in sorted(meta_now["campaigns"], key=lambda x: -x["spend"]):
        if c["spend"] == 0 and c["leads"] == 0:
            continue
        lines.append(f"{status_emoji(c['status'])} [Meta] {c['name']}")
        if is_topo_funil(c["name"]):
            lines.append(f"   {fmt_money(c['spend'])}  ·  Visitas: {fmt_int(c.get('profile_visits',0))}  ·  Shares: {fmt_int(c.get('shares',0))}  ·  Saves: {fmt_int(c.get('saves',0))}")
        else:
            cpl_c = c["spend"] / c["leads"] if c["leads"] else 0
            lines.append(f"   {fmt_money(c['spend'])}  ·  {c['leads']} leads  ·  CPL {fmt_money(cpl_c)}")
        lines.append("")
    for c in (google_now or {}).get("campaigns", []):
        if c["spend"] == 0 and c["leads"] == 0:
            continue
        lines.append(f"{status_emoji(c.get('status',''))} [Google] {c['name']}")
        lines.append(f"   {fmt_money(c['spend'])}  ·  {c['leads']} leads  ·  CPL {fmt_money(c['cpl'])}")
        lines.append("")

    lines += [
        "🟢 Ativa  ·  ⏸️ Pausada",
        "",
        "* CPL médio = investimento em campanhas de lead (Meta Fundo + Google) ÷ leads totais. Campanhas de marca/tráfego ficam fora do cálculo.",
        "Fontes: Meta Ads API + Google Ads API + Kommo CRM.",
    ]
    return "\n".join(lines)


def build_comment(meta_now, meta_prev, period_now, period_prev, kommo_now):
    """Análise estratégica sem emojis, sem travessões, com bolds. Sempre semanal."""
    s, e = period_now
    ps, pe = period_prev
    t = meta_now["total"]
    p = meta_prev["total"]
    ctr = (t["clicks"] / t["impressions"] * 100) if t["impressions"] else 0
    freq = (t["impressions"] / t["reach"]) if t["reach"] else 0
    click_to_lead = (t["leads"] / t["clicks"] * 100) if t["clicks"] else 0

    qual = kommo_now["qualified"]
    total_kommo = kommo_now["total_leads"]
    qual_pct = (qual / total_kommo * 100) if total_kommo else 0
    lost = kommo_now["lost"]
    lost_pct = (lost / total_kommo * 100) if total_kommo else 0
    lost_word = "leads perdidos" if lost != 1 else "lead perdido"

    status_summary = ", ".join(
        f"{n} em {STATUS_NAMES.get(sid, sid)}"
        for sid, n in sorted(kommo_now["status_dist"].items(), key=lambda x: -x[1])
    )

    # Público
    pubs = kommo_now["publicos"]
    sem_pub = sum(pubs.get("(sem público)", {}).values())
    real_pubs = {k: v for k, v in pubs.items() if k != "(sem público)"}
    pub_lines = []
    if real_pubs:
        ranked = []
        for name, dist in real_pubs.items():
            tot = sum(dist.values())
            q = sum(n for sid, n in dist.items() if sid in QUALIFIED_STATUSES)
            ranked.append((name, tot, q, q / tot * 100 if tot else 0))
        ranked.sort(key=lambda x: (-x[3], -x[1]))
        top = ranked[0]
        pub_lines.append(
            f"*Público com maior % de lead qualificado:* {top[0]} ({top[1]} leads, {top[3]:.0f}% qualificado)."
        )
        if sem_pub:
            pct = sem_pub / total_kommo * 100 if total_kommo else 0
            pub_lines.append(
                f"  Atenção: {sem_pub} de {total_kommo} leads ({pct:.0f}%) sem público preenchido. Padronizar pra próxima análise."
            )
    else:
        pub_lines.append(
            f"*Público com maior % de lead qualificado:* nenhum lead com público preenchido no Kommo (0 de {total_kommo}). Pedir pro time padronizar o preenchimento desse campo no contato."
        )

    # Criativo
    crvs = kommo_now["criativos"]
    sem_crv = sum(crvs.get("(sem criativo)", {}).values())
    real_crvs = {k: v for k, v in crvs.items() if k != "(sem criativo)"}
    crv_lines = []
    if real_crvs:
        ranked = []
        for name, dist in real_crvs.items():
            tot = sum(dist.values())
            q = sum(n for sid, n in dist.items() if sid in QUALIFIED_STATUSES)
            ranked.append((name, tot, q, q / tot * 100 if tot else 0))
        ranked.sort(key=lambda x: (-x[3], -x[1]))
        top = ranked[0]
        crv_lines.append(
            f"*Criativos com maior % de lead qualificado:* {top[0]} ({top[1]} leads, {top[3]:.0f}% qualificado)."
        )
        if sem_crv:
            crv_lines.append(f"  {sem_crv} de {total_kommo} leads sem criativo preenchido.")
    else:
        crv_lines.append(
            f"*Criativos com maior % de lead qualificado:* 0 de {total_kommo} leads tem o campo Criativo preenchido. Incluir no checklist de pré-atendimento."
        )

    # Perdas
    losses = kommo_now["losses"]
    loss_reasons = kommo_now["loss_reasons"]
    with_reason = [l for l in losses if l["reason_id"]]
    no_reason = [l for l in losses if not l["reason_id"]]
    perda_str = f"{lost} {lost_word} ({fmt_dec(lost_pct, 1)}%)"
    if lost:
        if with_reason:
            r = Counter(loss_reasons.get(l["reason_id"], "sem nome") for l in with_reason)
            motivos = ", ".join(f"{name} ({n})" for name, n in r.most_common())
            perda_str += f". Motivos: {motivos}."
            if no_reason:
                perda_str += f" {len(no_reason)} sem motivo cadastrado."
        else:
            perda_str += ", todos sem motivo cadastrado. Pedir pro time marcar motivo de perda no Kommo."

    lines = [
        "*Análise semanal estratégica. Leia antes de otimizar!*",
        "",
        f"*Contexto:* análise considera o período {br_date(s)} a {br_date(e)} (Meta) e leads criados no Kommo no mesmo período.",
        "",
        "*Leitura dos números (Meta):*",
        f"- CTR de {fmt_dec(ctr, 2)}% ({fmt_int(t['clicks'])} cliques / {fmt_int(t['impressions'])} impressões), benchmark imobiliário 1,2 a 1,8% pra mensagem.",
        f"- Frequência de {fmt_dec(freq, 2)}, {'saudável' if freq < 2.5 else 'atenção, sinal de desgaste'}.",
        f"- Taxa clique para lead de {fmt_dec(click_to_lead, 1)}% ({t['leads']}/{fmt_int(t['clicks'])}).",
        f"- CPL de {fmt_money(t['cpl'])}.",
        "",
    ]

    if p["leads"] or p["spend"]:
        leads_diff = t["leads"] - p["leads"]
        cpl_diff = t["cpl"] - p["cpl"]
        leads_pct = (leads_diff / p["leads"] * 100) if p["leads"] else None
        cpl_pct = (cpl_diff / p["cpl"] * 100) if p["cpl"] else None
        lines.append(f"*Comparativo vs semana anterior ({br_date(ps)} a {br_date(pe)}):*")
        if leads_pct is not None:
            sign = "+" if leads_diff >= 0 else ""
            lines.append(f"- Leads: {p['leads']} → {t['leads']} ({sign}{leads_diff} leads / {sign}{fmt_dec(leads_pct, 1)}%)")
        else:
            lines.append(f"- Leads: {p['leads']} → {t['leads']}")
        if cpl_pct is not None:
            sign = "+" if cpl_diff >= 0 else ""
            lines.append(f"- CPL: {fmt_money(p['cpl'])} → {fmt_money(t['cpl'])} ({sign}{fmt_money(cpl_diff)} / {sign}{fmt_dec(cpl_pct, 1)}%)")
        else:
            lines.append(f"- CPL: {fmt_money(p['cpl'])} → {fmt_money(t['cpl'])}")
        lines.append("")

    lines += [
        "*Análise qualitativa (Kommo):*",
        f"- *Número de leads qualificados:* {qual} de {total_kommo} leads no período ({qual_pct:.0f}%). Distribuição: {status_summary}." +
        (" *Atenção: gargalo na qualificação.*" if qual == 0 and total_kommo >= 5 else ""),
    ]
    lines += ["- " + l for l in pub_lines]
    lines += ["- " + l for l in crv_lines]
    lines.append("- *Possíveis combinações ou variações assertivas:* depende do cruzamento público + criativo nos contatos do Kommo.")
    lines.append(f"- *% e quantitativo de perda + motivos:* {perda_str}")
    lines.append("")

    # ─── Funil por empreendimento ─────────────────────────────────────
    by_emp = kommo_now.get("by_emp_status") or {}
    if by_emp:
        lines.append("*Funil por empreendimento:*")
        emp_sorted = sorted(by_emp.items(), key=lambda x: -sum(x[1].values()))
        for emp, dist in emp_sorted:
            tot = sum(dist.values())
            etapas = ", ".join(f"{n} {STATUS_NAMES.get(sid, sid)}" for sid, n in sorted(dist.items(), key=lambda x: -x[1]))
            lines.append(f"- *{emp}* ({tot} leads): {etapas}")
        lines.append("")

    # ─── Atividade por corretor ───────────────────────────────────────
    by_corr = kommo_now.get("by_corretor") or {}
    user_map = kommo_now.get("users") or {}
    if by_corr:
        lines.append("*Atividade por corretor:*")
        rows = []
        for ruid, dist in by_corr.items():
            total = sum(dist.values())
            ativo = sum(n for sid, n in dist.items() if sid != LOST_STATUS and sid != 142)
            propostas = sum(n for sid, n in dist.items() if sid in PROPOSAL_STATUSES)
            reunioes = sum(n for sid, n in dist.items() if sid in MEETING_STATUSES)
            qualif = sum(n for sid, n in dist.items() if sid in QUALIFIED_STATUSES)
            rows.append((ruid, total, ativo, propostas, reunioes, qualif))
        rows.sort(key=lambda x: -x[2])
        for ruid, total, ativo, propostas, reunioes, qualif in rows:
            nome = user_map.get(ruid, f"User {ruid}") if ruid else "(sem responsável)"
            extras = []
            if propostas: extras.append(f"*{propostas} proposta{'s' if propostas != 1 else ''}*")
            if reunioes: extras.append(f"*{reunioes} reunião/visita{'s' if reunioes != 1 else ''}*")
            if qualif: extras.append(f"{qualif} qualificado{'s' if qualif != 1 else ''}")
            extra_str = " — " + ", ".join(extras) if extras else ""
            lines.append(f"- *{nome}*: {ativo} ativo{'s' if ativo != 1 else ''} no funil ({total} total){extra_str}")
        lines.append("")

    # ─── Ritmo diário ──────────────────────────────────────────────────
    daily = kommo_now.get("daily") or {}
    if daily:
        lines.append("*Ritmo diário de leads:*")
        for d_iso in sorted(daily.keys()):
            d_obj = datetime.strptime(d_iso, "%Y-%m-%d").date()
            bar = "■" * min(daily[d_iso], 30)
            lines.append(f"- {d_obj.strftime('%d/%m')} ({d_obj.strftime('%a')[:3]}): {daily[d_iso]} {bar}")
        media = sum(daily.values()) / len(daily)
        lines.append(f"  Média: {media:.1f} leads/dia ao longo de {len(daily)} dias.")
        lines.append("")

    lines.append("*Sugestões pra próximos 30 dias:*")

    suggestions = []
    if qual == 0 and total_kommo >= 5:
        suggestions.append("*Prioridade alta:* destravar a qualificação. Conferir com o time se o pipeline (Lead Novo, Em Atendimento, Lead Qualificado) está sendo usado, ou se os leads estão parados sem follow-up.")
    if sem_pub > 0 or not real_crvs:
        suggestions.append("*Higiene de Kommo:* exigir preenchimento de Público + Criativo em 100% dos leads, e marcar motivo de perda nos Perdidos.")
    if ctr < 1.0:
        suggestions.append("Subir 2 ou 3 variações de criativo com ângulos diferentes do empreendimento (vista, planta, lifestyle, condições) pra empurrar o CTR.")
    suggestions.append("Manter investimento atual até fechar 30 dias rodando pra ter base estatística antes de mover variáveis com confiança.")
    for i, sg in enumerate(suggestions, 1):
        lines.append(f"{i}. {sg}")

    # Mensagens (pra enviar pro cliente) + ações (pra checklist na task de Otimizações)
    msgs = []
    actions = []

    msgs.append(
        f"Passando o relatório dessa semana: geramos {total_kommo} leads ({qual} qualificados, {qual_pct:.0f}%) ao CPL de {fmt_money(t['cpl'])}. Vou seguir monitorando a frequência das campanhas e o CPL nas próximas 72h pra antecipar qualquer ajuste de orçamento."
    )
    actions.append("Monitorar frequência das campanhas e CPL nas próximas 72h")

    if ctr < 1.0:
        msgs.append(
            f"O CTR fechou em {fmt_dec(ctr, 2)}% (abaixo do benchmark imobiliário de 1,2 a 1,8%). Pra próxima quinzena vou subir 2 ou 3 variações de criativo com ângulos diferentes (planta, vista, lifestyle, condições) pra empurrar o engajamento. Trago o comparativo no próximo relatório."
        )
        actions.append("Subir 2-3 variações de criativo com novos ângulos (planta, vista, lifestyle, condições) pra empurrar CTR")
    else:
        msgs.append(
            f"O CTR está saudável ({fmt_dec(ctr, 2)}%) e o CPL em {fmt_money(t['cpl'])}. Pra próxima rodada vou rodar um teste A/B com novos ângulos pra validar se conseguimos baixar ainda mais o CPL sem perder volume. Compartilho o resultado na próxima."
        )
        actions.append("Rodar teste A/B com novos ângulos de criativo pra baixar CPL")

    if qual_pct < 30 and total_kommo >= 5:
        msgs.append(
            f"Vou aproveitar a próxima semana pra olhar mais a fundo os públicos e a segmentação, já que a taxa de qualificação ficou em {qual_pct:.0f}%. Quero entender se estamos atraindo o perfil certo. No próximo relatório trago a análise e a proposta de ajuste."
        )
        actions.append("Analisar públicos e segmentação pra entender por que a taxa de qualificação está baixa")
    else:
        msgs.append(
            f"Qualidade do lead está dentro do esperado ({qual_pct:.0f}% qualificados). Vou manter a estratégia atual rodando mais 7 dias pra consolidar a base estatística antes de propor um aumento de investimento ou expansão de público."
        )
        actions.append("Manter estratégia atual por mais 7 dias e consolidar base estatística antes de escalar investimento")

    for _alert in (meta_now.get("varredura") or []):
        actions.append(_alert)

    lines.append("")
    lines.append("*Pra enviar pro cliente junto com o relatório (escolha 1):*")
    lines.append("")
    for i, m in enumerate(msgs, 1):
        lines.append(f"{i}. {m}")
        lines.append("")

    return "\n".join(lines), actions


# ---------------- ClickUp ----------------
def cu_put_description(task_id, description):
    return _http("PUT", f"https://api.clickup.com/api/v2/task/{task_id}",
                 headers={"Authorization": CLICKUP_TOKEN},
                 data={"description": description})


def _text_to_blocks(text):
    out = []
    lines = text.split("\n")
    counter = 0
    for i, line in enumerate(lines):
        pos = 0
        for m in re.finditer(r"\*([^*\n]+)\*", line):
            start, end = m.span()
            if start > pos:
                out.append({"text": line[pos:start], "attributes": {}})
            out.append({"text": m.group(1), "attributes": {"bold": True}})
            pos = end
        if pos < len(line):
            out.append({"text": line[pos:], "attributes": {}})
        if i < len(lines) - 1:
            counter += 1
            out.append({"text": "\n", "attributes": {"block-id": f"block-{counter:04d}"}})
    return out


def cu_post_comment(task_id, text):
    blocks = _text_to_blocks(text)
    return _http("POST", f"https://api.clickup.com/api/v2/task/{task_id}/comment",
                 headers={"Authorization": CLICKUP_TOKEN},
                 data={"comment_text": "", "comment": blocks})


def cu_delete_comment(comment_id):
    return _http("DELETE", f"https://api.clickup.com/api/v2/comment/{comment_id}",
                 headers={"Authorization": CLICKUP_TOKEN})


def cu_get_comments(task_id):
    d = _http("GET", f"https://api.clickup.com/api/v2/task/{task_id}/comment",
              headers={"Authorization": CLICKUP_TOKEN})
    return d.get("comments", [])


def cu_get_task(task_id):
    return _http("GET", f"https://api.clickup.com/api/v2/task/{task_id}",
                 headers={"Authorization": CLICKUP_TOKEN})


def cu_create_checklist(task_id, name):
    return _http("POST", f"https://api.clickup.com/api/v2/task/{task_id}/checklist",
                 headers={"Authorization": CLICKUP_TOKEN},
                 data={"name": name})


def cu_delete_checklist(checklist_id):
    return _http("DELETE", f"https://api.clickup.com/api/v2/checklist/{checklist_id}",
                 headers={"Authorization": CLICKUP_TOKEN})


def cu_add_checklist_item(checklist_id, name):
    return _http("POST", f"https://api.clickup.com/api/v2/checklist/{checklist_id}/checklist_item",
                 headers={"Authorization": CLICKUP_TOKEN},
                 data={"name": name})


CHECKLIST_NAME_AUTO = "📊 Ações da semana (auto)"


def sync_checklist(task_id, actions):
    try:
        task = cu_get_task(task_id)
        for cl in (task.get("checklists") or []):
            if cl.get("name") == CHECKLIST_NAME_AUTO:
                try:
                    cu_delete_checklist(cl["id"])
                except Exception as ex:
                    print(f"  aviso: falha ao deletar checklist antigo: {ex}", file=sys.stderr)
    except Exception as ex:
        print(f"  aviso: falha ao listar checklists: {ex}", file=sys.stderr)
    cl_resp = cu_create_checklist(task_id, CHECKLIST_NAME_AUTO)
    cl_id = (cl_resp.get("checklist") or {}).get("id")
    if cl_id:
        for act in actions:
            cu_add_checklist_item(cl_id, act)
    return cl_id


# ---------------- Main ----------------
def _fetch_period(s, e, ps, pe, status_map, label):
    print(f"→ {label}: Meta atual ({s} a {e})...")
    m_now = meta_insights(META_AD_ACCOUNT, str(s), str(e), status_map)
    print(f"   gasto={fmt_money(m_now['total']['spend'])} leads_meta={m_now['total']['leads']}")
    print(f"→ {label}: Meta anterior ({ps} a {pe})...")
    m_prev = meta_insights(META_AD_ACCOUNT, str(ps), str(pe), status_map)
    print(f"   gasto={fmt_money(m_prev['total']['spend'])} leads_meta={m_prev['total']['leads']}")

    print(f"→ {label}: Google Ads atual ({s} a {e})...")
    g_now = google_ads_insights(s, e) if GADS_AVAILABLE else {"total": {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}, "campaigns": []}
    print(f"   gasto={fmt_money(g_now['total']['spend'])} leads_google={g_now['total']['leads']}")
    print(f"→ {label}: Google Ads anterior ({ps} a {pe})...")
    g_prev = google_ads_insights(ps, pe) if GADS_AVAILABLE else {"total": {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}, "campaigns": []}
    print(f"   gasto={fmt_money(g_prev['total']['spend'])} leads_google={g_prev['total']['leads']}")

    print(f"→ {label}: Kommo ({s} a {e})...")
    s_ts = int(datetime.combine(s, datetime.min.time(), tzinfo=BRT).timestamp())
    e_ts = int(datetime.combine(e, datetime.max.time().replace(microsecond=0), tzinfo=BRT).timestamp())
    k_now = kommo_aggregate(s_ts, e_ts)
    print(f"   total_leads={k_now['total_leads']} qualif={k_now['qualified']} vendas={len(k_now.get('vendas') or [])} perdidos={k_now['lost']}")
    print(f"→ {label}: Kommo anterior ({ps} a {pe})...")
    ps_ts = int(datetime.combine(ps, datetime.min.time(), tzinfo=BRT).timestamp())
    pe_ts = int(datetime.combine(pe, datetime.max.time().replace(microsecond=0), tzinfo=BRT).timestamp())
    k_prev = kommo_aggregate(ps_ts, pe_ts)
    print(f"   total_leads={k_prev['total_leads']} qualif={k_prev['qualified']} vendas={len(k_prev.get('vendas') or [])}")

    return m_now, m_prev, g_now, g_prev, k_now, k_prev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="aplica mudanças (default: dry-run)")
    ap.add_argument("--force-mode", choices=["semanal", "mensal"], help="força um modo")
    ap.add_argument("--date", help="YYYY-MM-DD pra simular outra data")
    args = ap.parse_args()

    today = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else br_today()
    today = effective_today(today)
    mode = decide_mode(today, args.force_mode)

    print(f"== IMR / MME Vacation Club — description: {mode}, comentário: sempre semanal ==")
    print(f"Hoje (BRT): {today}  |  Apply: {args.apply}  |  Google Ads: {'ON' if GADS_AVAILABLE else 'OFF'}")
    print("→ Meta Ads (campanhas)...")
    status_map = meta_campaign_status_map(META_AD_ACCOUNT)
    print(f"   {len(status_map)} campanhas mapeadas\n")

    # Sempre puxa dados SEMANAIS (alimentam o comentário)
    (s_sem, e_sem), (ps_sem, pe_sem) = compute_periods(today, "semanal")
    print(f"=== dados semanais ({s_sem} a {e_sem}) — pro comentário ===")
    sem_m, sem_m_prev, sem_g, sem_g_prev, sem_k, sem_k_prev = _fetch_period(s_sem, e_sem, ps_sem, pe_sem, status_map, "semanal")

    if mode == "semanal":
        description = build_description(sem_m, sem_m_prev, sem_g, sem_g_prev, (s_sem, e_sem), (ps_sem, pe_sem), "semanal", sem_k, sem_k_prev)
        target_task = TASK_RELATORIO
    else:
        (s_men, e_men), (ps_men, pe_men) = compute_periods(today, "mensal")
        print(f"\n=== dados mensais ({s_men} a {e_men}) — pra description ===")
        men_m, men_m_prev, men_g, men_g_prev, men_k, men_k_prev = _fetch_period(s_men, e_men, ps_men, pe_men, status_map, "mensal")
        description = build_description(men_m, men_m_prev, men_g, men_g_prev, (s_men, e_men), (ps_men, pe_men), "mensal", men_k, men_k_prev)
        target_task = TASK_RELATORIO

    # build_comment ainda na assinatura original (será adaptado num próximo passo pra incluir Google)
    comment, actions = build_comment(sem_m, sem_m_prev, (s_sem, e_sem), (ps_sem, pe_sem), sem_k)

    print(f"\n→ Description target: {target_task} ({mode})")
    print(f"→ Comment target: {TASK_OTIMIZACOES} (sempre semanal)\n")

    if not args.apply:
        print("========== DRY RUN — DESCRIPTION ==========")
        print(description)
        print("\n========== DRY RUN — COMMENT ==========")
        print(comment)
        print("\n(use --apply pra aplicar no ClickUp)")
        return

    cu_put_description(target_task, description)
    print(f"✓ description atualizada em https://app.clickup.com/t/{target_task}")

    existing = cu_get_comments(TASK_OTIMIZACOES)
    for c in existing:
        try:
            cu_delete_comment(c["id"])
        except Exception as ex:
            print(f"  aviso: falha ao excluir comment {c['id']}: {ex}", file=sys.stderr)
    r = cu_post_comment(TASK_OTIMIZACOES, comment)
    print(f"✓ comentário postado em https://app.clickup.com/t/{TASK_OTIMIZACOES} (id={r.get('id')})")

    cl_id = sync_checklist(TASK_OTIMIZACOES, actions)
    if cl_id:
        print(f"✓ checklist '{CHECKLIST_NAME_AUTO}' atualizado com {len(actions)} ações (id={cl_id})")


if __name__ == "__main__":
    main()
