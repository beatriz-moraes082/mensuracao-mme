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
TASK_RELATORIO   = os.environ.get("MME_TASK_RELATORIO",   "86ahp619r")  # fallback se lookup falhar
TASK_OTIMIZACOES = os.environ.get("MME_TASK_OTIMIZACOES", "86ahhq9rk")  # MME Vacation Club — lista 📈 Otimizações
# Alias retrocompat com a estrutura do Maia (build_description usa TASK_SEMANAL/TASK_MENSAL):
TASK_SEMANAL = TASK_RELATORIO
TASK_MENSAL  = TASK_RELATORIO

# Lookup dinâmico na lista 📊 Relatórios (canônica) — lógica acordada com Ana 2026-06-01:
# TODAS as tasks têm due_date; 1ª seg do mês recebe MENSAL, demais semanas recebem SEMANAL.
RELATORIOS_LIST_ID = "901323122510"
CLICKUP_NAME_FILTER = os.environ.get("MME_CLICKUP_NAME_FILTER", "Ipioca Mar Resort")

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

# Pipelines do Kommo IMR. ATENÇÃO: status 142 ("Venda ganha" built-in) significa
# coisas diferentes por pipeline — só conta como venda quando vem do Closer.
SDR_PIPELINE_ID    = 12716679  # 142 aqui = "Reunião realizada", NÃO venda
CLOSER_PIPELINE_ID = 12719415  # 142 aqui = venda real
DUQUE_PIPELINE_ID  = 12721167  # nutrição

# Usuários do Kommo IMR que NÃO são corretores (bots de importação, conta admin etc.)
# Filtrados do ranking "Atividade por corretor" e "Corretor mais ativo"
BOT_USERS = {"Trilha", "MME Vacation", "MME Vacation Club"}


def _comp_label_for(mode, s_prev, e_prev):
    """Label do comparativo que respeita o modo do período (não usar 'vs semana anterior' pra mensal/quinzenal)."""
    days = (e_prev - s_prev).days + 1
    if mode == "mensal":
        return "vs período anterior"
    if days == 15:
        return "vs quinzena anterior"
    if days == 7 and s_prev.day == 1:
        return "vs primeiros 7 dias anteriores"
    return "vs semana anterior"


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
            "follows": _action_value(actions, "onsite_conversion.follow"),
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


def kommo_closer_won(start_ts, end_ts):
    """Vendas REAIS: leads do pipeline Closer com status 142 fechados (closed_at) no período.
    Filtra por closed_at (não created_at) porque vendas costumam ser criadas em períodos anteriores."""
    vendas = []
    page = 1
    while True:
        d = kommo_get(
            f"leads?filter[pipeline_id]={CLOSER_PIPELINE_ID}"
            f"&filter[closed_at][from]={start_ts}&filter[closed_at][to]={end_ts}"
            f"&limit=250&page={page}"
        )
        batch = (d.get("_embedded") or {}).get("leads", [])
        if not batch:
            break
        for l in batch:
            if l.get("status_id") == WON_STATUS:
                vendas.append({
                    "id": l["id"], "name": l.get("name") or "(sem nome)",
                    "price": float(l.get("price") or 0),
                    "corretor_id": l.get("responsible_user_id"),
                    "closed_at": l.get("closed_at"),
                })
        if len(batch) < 250:
            break
        page += 1
    return vendas


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
        # IMPORTANTE: NÃO contar vendas aqui — status 142 no SDR/Duque significa "Reunião realizada"
        # ou outro estágio terminal, não venda. Vendas reais vêm de kommo_closer_won() abaixo.

    # Vendas reais: query separada filtrada por pipeline Closer + closed_at no período
    vendas = kommo_closer_won(start_ts, end_ts)

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
    """Description do IMR: Visão Geral consolidada + Meta + Google."""
    s_now, e_now = period_now
    s_prev, e_prev = period_prev
    mt, mp = meta_now["total"], meta_prev["total"]
    gt = (google_now or {}).get("total") or {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}
    gp = (google_prev or {}).get("total") or {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}

    total_invest_now  = mt["spend"] + gt["spend"]
    total_invest_prev = mp["spend"] + gp["spend"]
    total_leads_now   = mt["leads"] + gt["leads"]
    total_leads_prev  = mp["leads"] + gp["leads"]
    lead_spend_now  = mt.get("lead_spend", mt["spend"]) + gt["spend"]
    lead_spend_prev = mp.get("lead_spend", mp["spend"]) + gp["spend"]
    cpl_medio_now  = lead_spend_now  / total_leads_now  if total_leads_now  else 0.0
    cpl_medio_prev = lead_spend_prev / total_leads_prev if total_leads_prev else 0.0

    def _delta_str(n, p, is_money=False):
        if not p:
            return f"(vs {fmt_money(p) if is_money else p})"
        d = n - p
        pct = (d / p * 100)
        sign = "+" if d >= 0 else ""
        d_str = f"{sign}{fmt_money(d)}" if is_money else f"{sign}{d}"
        return f"({fmt_money(p) if is_money else p} → {fmt_money(n) if is_money else n}, {d_str} / {sign}{pct:.1f}%)"

    lines = [
        "📊 RESULTADOS DAS CAMPANHAS",
        f"Período analisado: {period_label(s_now, e_now, mode)} → {br_date(s_now)} a {br_date(e_now)}",
        "",
        "🎯 VISÃO GERAL (Meta + Google)",
        f"Investimento total: {fmt_money(total_invest_now)}",
        f"Leads gerados: {total_leads_now}",
        f"CPL médio: {fmt_money(cpl_medio_now)}",
        "",
    ]

    if total_leads_prev or total_invest_prev:
        comp_label = _comp_label_for(mode, s_prev, e_prev)
        lines += [
            f"📈 Comparativo {comp_label} ({br_date(s_prev)} a {br_date(e_prev)}):",
            f"Leads: {_delta_str(total_leads_now, total_leads_prev)}",
            f"CPL: {_delta_str(cpl_medio_now, cpl_medio_prev, is_money=True)}",
            f"Investimento: {_delta_str(total_invest_now, total_invest_prev, is_money=True)}",
            "",
        ]

    # ── Meta Ads ─────────────────────────────────────────────────────────────
    lines += ["🔵 META ADS", ""]
    fundo_camps = [c for c in meta_now["campaigns"] if not is_topo_funil(c["name"])]
    fundo_spend = sum(c["spend"] for c in fundo_camps)
    fundo_leads = sum(c["leads"] for c in fundo_camps)
    fundo_cpl   = fundo_spend / fundo_leads if fundo_leads else 0
    if fundo_camps:
        lines += [
            "Campanha de Leads (Fundo de Funil)",
            f"Investido = {fmt_money(fundo_spend)}",
            f"Leads: {fundo_leads}",
            f"CPL: {fmt_money(fundo_cpl)}",
            "",
        ]
        fundo_prev_camps = [c for c in meta_prev["campaigns"] if not is_topo_funil(c["name"])]
        f_p_spend = sum(c["spend"] for c in fundo_prev_camps)
        f_p_leads = sum(c["leads"] for c in fundo_prev_camps)
        f_p_cpl   = f_p_spend / f_p_leads if f_p_leads else 0
        if f_p_leads or f_p_spend:
            lines += [
                f"{_comp_label_for(mode, s_prev, e_prev)}:",
                f"Leads: {_delta_str(fundo_leads, f_p_leads)}",
                f"CPL: {_delta_str(fundo_cpl, f_p_cpl, is_money=True)}",
                "",
            ]

    topo_camps = [c for c in meta_now["campaigns"] if is_topo_funil(c["name"])]
    topo_spend  = sum(c["spend"] for c in topo_camps)
    topo_visits  = sum(c.get("profile_visits", 0) for c in topo_camps)
    topo_follows = sum(c.get("follows", 0) for c in topo_camps)
    topo_shares  = sum(c.get("shares", 0) for c in topo_camps)
    topo_saves   = sum(c.get("saves", 0) for c in topo_camps)
    if topo_camps:
        lines += [
            "Campanha de Marca (Topo de Funil)",
            f"Investido: {fmt_money(topo_spend)}",
            f"Visitas ao perfil: {fmt_int(topo_visits)}",
            f"Número de seguidores: {fmt_int(topo_follows)}",
            f"Compartilhamentos: {fmt_int(topo_shares)}",
            f"Salvamentos: {fmt_int(topo_saves)}",
            "",
        ]

    # ── Google Ads ──────────────────────────────────────────────────────────
    if gt["spend"] > 0 or gt["leads"] > 0:
        lines += ["🟢 GOOGLE ADS", ""]
        for c in (google_now or {}).get("campaigns", []):
            if c["spend"] == 0 and c["leads"] == 0:
                continue
            lines.append(f"{status_emoji(c.get('status',''))} {c['name']}")
            lines.append("")
            lines.append(f"Investido = {fmt_money(c['spend'])}")
            lines.append(f"Leads: {c['leads']}")
            lines.append(f"CPL: {fmt_money(c['cpl'])}")
            lines.append("")

    return "\n".join(lines)


def build_comment(meta_now, meta_prev, google_now, google_prev, period_now, period_prev, kommo_now):
    """Análise estratégica IMR/MME (resort multipropriedade). Sempre semanal.
    Foco: mídia paga consolidada (Meta+Google) + funil Kommo (qualificação, vendas, perdas)."""
    s, e = period_now
    ps, pe = period_prev
    mt, mp = meta_now["total"], meta_prev["total"]
    gt = (google_now or {}).get("total") or {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}
    gp = (google_prev or {}).get("total") or {"spend": 0.0, "impressions": 0, "clicks": 0, "leads": 0, "cpl": 0.0}

    # ── Mídia paga consolidada (Meta+Google) — leads REAIS de aquisição ─────
    midia_leads_now  = mt["leads"] + gt["leads"]
    midia_leads_prev = mp["leads"] + gp["leads"]
    midia_invest_now  = mt["spend"] + gt["spend"]
    midia_invest_prev = mp["spend"] + gp["spend"]
    lead_spend_now  = mt.get("lead_spend", mt["spend"]) + gt["spend"]
    lead_spend_prev = mp.get("lead_spend", mp["spend"]) + gp["spend"]
    cpl_medio_now  = lead_spend_now  / midia_leads_now  if midia_leads_now  else 0.0
    cpl_medio_prev = lead_spend_prev / midia_leads_prev if midia_leads_prev else 0.0

    # Meta isolado
    meta_ctr  = (mt["clicks"] / mt["impressions"] * 100) if mt["impressions"] else 0
    meta_freq = (mt["impressions"] / mt["reach"]) if mt["reach"] else 0

    # Funil Kommo (do período — mas IMR tem muito bot/importação no CRM,
    # então o "total_leads" do Kommo inclui spam de nutrição/duque)
    qual = kommo_now.get("qualified", 0)
    vendas = kommo_now.get("vendas") or []
    receita = kommo_now.get("receita") or 0
    perdidos = kommo_now.get("lost", 0)
    loss_reasons_map = kommo_now.get("loss_reasons") or {}
    loss_counter = Counter()
    for l in (kommo_now.get("losses") or []):
        rid = l.get("reason_id")
        if rid:
            loss_counter[rid] += 1

    lines = [
        "*Análise semanal estratégica. Leia antes de otimizar!*",
        "",
        f"*Contexto:* análise considera o período {br_date(s)} a {br_date(e)} (Meta Ads + Google Ads) e funil Kommo do mesmo período.",
        "",
        "*Leitura dos números (mídia paga):*",
        f"- Investimento total: {fmt_money(midia_invest_now)} (Meta {fmt_money(mt['spend'])} + Google {fmt_money(gt['spend'])}).",
        f"- Leads totais: {midia_leads_now} (Meta {mt['leads']} + Google {gt['leads']}).",
        f"- CPL médio: {fmt_money(cpl_medio_now)} (lead_spend / leads totais; campanhas de marca/tráfego ficam fora).",
        f"- Meta: CTR {fmt_dec(meta_ctr, 2)}% (benchmark turismo/lazer 1,0 a 1,5%), frequência {fmt_dec(meta_freq, 2)} ({'saudável' if meta_freq < 2.5 else 'sinal de desgaste'}).",
    ]
    if gt["impressions"]:
        g_ctr = gt["clicks"] / gt["impressions"] * 100
        lines.append(f"- Google: CTR {fmt_dec(g_ctr, 2)}%, CPC R$ {gt['spend'] / gt['clicks']:.2f}." if gt["clicks"] else "- Google: sem cliques registrados.")
    lines.append("")

    # Comparativo
    if midia_leads_prev or midia_invest_prev:
        leads_diff = midia_leads_now - midia_leads_prev
        cpl_diff = cpl_medio_now - cpl_medio_prev
        leads_pct = (leads_diff / midia_leads_prev * 100) if midia_leads_prev else None
        cpl_pct = (cpl_diff / cpl_medio_prev * 100) if cpl_medio_prev else None
        lines.append(f"*Comparativo vs período anterior ({br_date(ps)} a {br_date(pe)}):*")
        if leads_pct is not None:
            sign = "+" if leads_diff >= 0 else ""
            lines.append(f"- Leads: {midia_leads_prev} → {midia_leads_now} ({sign}{leads_diff} / {sign}{fmt_dec(leads_pct, 1)}%)")
        if cpl_pct is not None:
            sign = "+" if cpl_diff >= 0 else ""
            lines.append(f"- CPL: {fmt_money(cpl_medio_prev)} → {fmt_money(cpl_medio_now)} ({sign}{fmt_money(cpl_diff)} / {sign}{fmt_dec(cpl_pct, 1)}%)")
        lines.append("")

    # Análise qualitativa Kommo (foca em qualificação + vendas + perdas, não no total_leads inflado por bot/nutrição)
    lines += [
        "*Funil comercial (Kommo):*",
        f"- *Leads qualificados pelo SDR:* {qual} no período" + (" (atenção: zero qualificado com volume de mídia positivo — verificar abordagem do SDR)" if qual == 0 and midia_leads_now >= 5 else "."),
    ]
    if vendas:
        receita_str = f" — {fmt_money(receita)} faturado" if receita > 0 else ""
        lines.append(f"- *Vendas fechadas:* {len(vendas)} no período{receita_str}.")
        users = kommo_now.get("users") or {}
        corr_vendas = Counter()
        for v in vendas:
            corr = users.get(v["corretor_id"], "(sem closer)") if v["corretor_id"] else "(sem closer)"
            corr_vendas[corr] += 1
        if corr_vendas:
            top_corr, top_n = corr_vendas.most_common(1)[0]
            lines.append(f"- *Closer com mais vendas:* {top_corr} ({top_n} venda{'s' if top_n != 1 else ''} de {len(vendas)}).")
    else:
        lines.append("- *Vendas fechadas:* nenhuma no período.")
    if perdidos:
        top_perdas = loss_counter.most_common(3)
        if top_perdas:
            motivos = ", ".join(f"{loss_reasons_map.get(rid, '?')} ({n})" for rid, n in top_perdas)
            lines.append(f"- *Perdas no período:* {perdidos} leads. Top motivos: {motivos}.")
    lines.append("")

    # Sugestões customizadas pra resort/multipropriedade
    lines.append("*Sugestões pra próxima semana:*")
    suggestions = []
    # Sinal: Google subindo ou caindo absurdamente
    if gp["leads"] and gt["leads"]:
        g_leads_diff_pct = (gt["leads"] - gp["leads"]) / gp["leads"] * 100
        if g_leads_diff_pct < -50:
            suggestions.append(f"*Google Ads:* leads caíram {abs(g_leads_diff_pct):.0f}% vs período anterior. Verificar status das campanhas (a PMax pode estar pausada), saldo da conta e qualidade do criativo.")
        elif gt["cpl"] > mt.get("cpl", 0) * 2 and mt.get("cpl", 0) > 0:
            suggestions.append(f"*Google Ads:* CPL ({fmt_money(gt['cpl'])}) está 2x acima do Meta ({fmt_money(mt['cpl'])}). Avaliar se vale realocar parte do investimento de PMax pro Meta, ou ajustar a estratégia de bid do PMax.")
    # Sinal: vendas zero apesar de leads qualificados
    if vendas and len(vendas) >= 1 and qual >= 5 and len(vendas) < qual * 0.1:
        suggestions.append(f"*Conversão lead → venda baixa:* {qual} qualificados geraram só {len(vendas)} venda(s) ({len(vendas)/qual*100:.0f}%). Vale alinhar com o time comercial o tempo de resposta e o script de abordagem.")
    # Sinal: motivos de perda alarmantes
    if loss_counter:
        top_motivo, top_n = loss_counter.most_common(1)[0]
        top_motivo_name = loss_reasons_map.get(top_motivo, "?")
        if "não responde" in top_motivo_name.lower() or "atende" in top_motivo_name.lower():
            suggestions.append(f"*Velocidade de atendimento:* '{top_motivo_name}' é o principal motivo de perda ({top_n}). Vale testar resposta em até 5min após captação (estudos mostram queda de 80% na conversão após 1h).")
    # Sinal: CPL meta acima de benchmark
    if mt.get("cpl", 0) > 30:
        suggestions.append(f"*CPL Meta acima da régua:* {fmt_money(mt['cpl'])}. Testar 2-3 novos criativos focados em diferentes pilares do produto (multipropriedade, retorno financeiro, experiência de uso, programa de afiliados).")
    if not suggestions:
        suggestions.append("Manter estratégia atual e monitorar próxima semana — números dentro do esperado.")
    for i, sg in enumerate(suggestions, 1):
        lines.append(f"{i}. {sg}")

    # Mensagens prontas pra enviar pro cliente + ações pro checklist
    msgs = []
    actions = []

    qual_pct = (qual / midia_leads_now * 100) if midia_leads_now else 0
    msgs.append(
        f"Passando o relatório dessa semana: geramos {midia_leads_now} leads ({qual} qualificados pelo SDR) ao CPL médio de {fmt_money(cpl_medio_now)}. " +
        (f"Fechamos {len(vendas)} venda(s) no período. " if vendas else "") +
        f"Vou monitorar a frequência das campanhas e o CPL nas próximas 72h pra antecipar qualquer ajuste de orçamento."
    )
    actions.append("Monitorar frequência das campanhas e CPL Meta+Google nas próximas 72h")

    if meta_ctr < 1.0:
        msgs.append(
            f"O CTR fechou em {fmt_dec(meta_ctr, 2)}% (abaixo do benchmark turismo de 1,0 a 1,5%). Pra próxima rodada vou subir 2 a 3 variações de criativo com ângulos diferentes (experiência de uso, retorno financeiro, programa de afiliados) pra empurrar o engajamento. Trago o comparativo no próximo relatório."
        )
        actions.append("Subir 2-3 variações de criativo com novos ângulos (experiência, retorno financeiro, programa de afiliados)")
    else:
        msgs.append(
            f"O CTR está saudável ({fmt_dec(meta_ctr, 2)}%) e o CPL em {fmt_money(cpl_medio_now)}. Pra próxima rodada vou rodar um teste A/B com novos ângulos pra validar se conseguimos baixar ainda mais o CPL sem perder volume. Compartilho o resultado na próxima."
        )
        actions.append("Rodar teste A/B com novos ângulos de criativo pra baixar CPL")

    if gp["leads"] and gt["leads"] and (gt["leads"] - gp["leads"]) / gp["leads"] < -0.5:
        msgs.append(
            f"O Google Ads caiu de {gp['leads']} pra {gt['leads']} leads vs período anterior — vou verificar status das campanhas (incluindo PMax que aparece pausada) e qualidade do criativo. Subo o aprendizado no próximo relatório."
        )
        actions.append("Verificar status das campanhas Google (PMax pausada?) e qualidade dos criativos")
    elif vendas and qual >= 5 and len(vendas) < qual * 0.1:
        msgs.append(
            f"Esta semana fechamos {len(vendas)} venda(s) com {qual} qualificados. Vou aprofundar a análise da jornada do lead qualificado até a venda pra entender onde estamos perdendo conversão e proponho ajuste no próximo relatório."
        )
        actions.append("Analisar jornada lead qualificado → venda e identificar gargalos de conversão")
    else:
        msgs.append(
            f"Vou manter a estratégia atual rodando mais 7 dias pra consolidar a base estatística antes de propor um aumento de investimento ou nova expansão de público."
        )
        actions.append("Consolidar base estatística por mais 7 dias antes de escalar investimento")

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
def find_task_for_period(mode):
    """Busca task na lista 📊 Relatórios (canônica) pelo nome do cliente + due_date.
    Lógica acordada com Ana (2026-06-01): TODAS as tasks têm due_date; o que muda é o conteúdo.
    - mode == "mensal": busca task com due_date = 1ª seg do mês atual
    - mode == "semanal": busca task com due_date = última segunda
    Retorna task_id (str) ou None (chamador usa fallback)."""
    is_monthly = (mode == "mensal")
    today = date.today()
    if is_monthly:
        first_of_month = today.replace(day=1)
        days_to_monday = (7 - first_of_month.weekday()) % 7
        target_monday = first_of_month + timedelta(days=days_to_monday)
    else:
        target_monday = today - timedelta(days=today.weekday())
    window_start_ms = int(datetime.combine(target_monday - timedelta(days=1), datetime.min.time()).timestamp() * 1000)
    window_end_ms = int(datetime.combine(target_monday + timedelta(days=1), datetime.max.time()).timestamp() * 1000)

    all_tasks = []
    page = 0
    while page < 10:
        url = f"https://api.clickup.com/api/v2/list/{RELATORIOS_LIST_ID}/task?archived=false&include_closed=true&page={page}"
        d = _http("GET", url, headers={"Authorization": CLICKUP_TOKEN})
        batch = d.get("tasks", [])
        if not batch:
            break
        all_tasks.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    for t in all_tasks:
        if CLICKUP_NAME_FILTER.lower() not in (t.get("name") or "").lower():
            continue
        due = t.get("due_date")
        if due is None:
            continue
        try:
            due_ms = int(due)
        except (TypeError, ValueError):
            continue
        if window_start_ms <= due_ms <= window_end_ms:
            return t["id"]
    return None


def cu_put_description(task_id, description):
    # Usa markdown_content pra renderizar **negrito** / listas (field 'description' plain não renderiza).
    # Converte *texto* (escrito pelo build) em **texto** (markdown válido).
    md = re.sub(r"\*([^*\n]+)\*", r"**\1**", description)
    return _http("PUT", f"https://api.clickup.com/api/v2/task/{task_id}",
                 headers={"Authorization": CLICKUP_TOKEN},
                 data={"markdown_content": md})


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
        fallback_task = TASK_RELATORIO
    else:
        (s_men, e_men), (ps_men, pe_men) = compute_periods(today, "mensal")
        print(f"\n=== dados mensais ({s_men} a {e_men}) — pra description ===")
        men_m, men_m_prev, men_g, men_g_prev, men_k, men_k_prev = _fetch_period(s_men, e_men, ps_men, pe_men, status_map, "mensal")
        description = build_description(men_m, men_m_prev, men_g, men_g_prev, (s_men, e_men), (ps_men, pe_men), "mensal", men_k, men_k_prev)
        fallback_task = TASK_RELATORIO

    comment, actions = build_comment(sem_m, sem_m_prev, sem_g, sem_g_prev, (s_sem, e_sem), (ps_sem, pe_sem), sem_k)

    # Lookup dinâmico na 📊 Relatórios — escrita oficial vai aqui
    target_task = find_task_for_period(mode)
    if target_task:
        print(f"\n→ Description target (📊 Relatórios): {target_task} ({mode})")
    else:
        target_task = fallback_task
        print(f"\n⚠️ Nenhuma task '{CLICKUP_NAME_FILTER}' na 📊 Relatórios com due_date alvo — usando fallback {target_task}")
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
