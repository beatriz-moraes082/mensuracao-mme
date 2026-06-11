"""
Busca métricas da régua de email no Mailchimp (audiência MME Vacation Club).
Saída: data/mailchimp.json

Estrutura do output:
{
  "fetched_at": ISO timestamp,
  "audience": { name, member_count, ... },
  "campaigns": [ {id, subject, type, sent_at, sent, opens, clicks, unsub, ...} ],
  "by_subject": { subject: { n, sent, opens, clicks, unsub, ... } },  # agregado pela régua
  "by_month":   { "YYYY-MM": { sent, opens, clicks, unsub } }
}
"""

import json, os, requests
from datetime import datetime, timezone
from pathlib import Path
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

API_KEY = os.environ.get("MAILCHIMP_API_KEY")
if not API_KEY:
    raise KeyError("MAILCHIMP_API_KEY ausente — exporte no .env ou GitHub secret")

# Data center é o sufixo da key (ex: 'us17')
if "-" not in API_KEY:
    raise ValueError("API key sem data center (esperado formato 'xxx-us17')")
DC = API_KEY.split("-")[-1]

BASE = f"https://{DC}.api.mailchimp.com/3.0"
H = {"Authorization": f"Bearer {API_KEY}"}


def mc_get(path, **params):
    r = requests.get(f"{BASE}{path}", headers=H, params=params, timeout=30)
    if not r.ok:
        print(f"  ⚠️  {r.status_code} em {path}: {r.text[:150]}")
        return {}
    return r.json()


def fetch_audience():
    """Retorna a primeira audience (cliente IMR só tem uma)."""
    data = mc_get("/lists", count=10)
    lists = data.get("lists", [])
    if not lists:
        return None
    lst = lists[0]
    stats = lst.get("stats", {})
    return {
        "id": lst["id"],
        "name": lst["name"],
        "member_count": stats.get("member_count", 0),
        "unsubscribe_count": stats.get("unsubscribe_count", 0),
        "cleaned_count": stats.get("cleaned_count", 0),
        "open_rate": stats.get("open_rate", 0),
        "click_rate": stats.get("click_rate", 0),
        "campaign_count": stats.get("campaign_count", 0),
        "last_send_date": stats.get("last_send_date", ""),
        "date_created": lst.get("date_created", ""),
    }


def fetch_all_campaigns():
    """Pagina todas as campaigns (status sent + sending da régua), retornando lista flat."""
    out, offset = [], 0
    while True:
        data = mc_get(
            "/campaigns",
            count=200,
            offset=offset,
            sort_field="send_time",
            sort_dir="DESC",
        )
        batch = data.get("campaigns", []) or []
        out.extend(batch)
        if len(batch) < 200:
            break
        offset += 200
    print(f"  {len(out)} campaigns no total")
    return out


def fetch_campaign_report(cid):
    rep = mc_get(f"/reports/{cid}")
    if not rep:
        return None
    opens = rep.get("opens", {}) or {}
    clicks = rep.get("clicks", {}) or {}
    bounces = rep.get("bounces", {}) or {}
    return {
        "sent": rep.get("emails_sent", 0) or 0,
        "opens_total": opens.get("opens_total", 0) or 0,
        "unique_opens": opens.get("unique_opens", 0) or 0,
        "open_rate": (opens.get("open_rate", 0) or 0) * 100,
        "clicks_total": clicks.get("clicks_total", 0) or 0,
        "unique_clicks": clicks.get("unique_subscriber_clicks", 0) or 0,
        "click_rate": (clicks.get("click_rate", 0) or 0) * 100,
        "unsubscribed": rep.get("unsubscribed", 0) or 0,
        "hard_bounces": bounces.get("hard_bounces", 0) or 0,
        "soft_bounces": bounces.get("soft_bounces", 0) or 0,
    }


def main():
    print("=== Mailchimp Fetch ===")
    print(f"Data center: {DC}")

    aud = fetch_audience()
    if not aud:
        print("⚠️  Nenhuma audience encontrada.")
        return
    print(f"Audience: '{aud['name']}' · {aud['member_count']} membros")

    raw = fetch_all_campaigns()
    enriched = []
    for c in raw:
        sent = c.get("emails_sent", 0) or 0
        if sent == 0:
            continue
        # Tipo: 'automation-email' (régua) ou 'regular' (broadcast)
        ctype = c.get("type", "regular")
        subject = (c.get("settings", {}) or {}).get("subject_line", "—")
        title = (c.get("settings", {}) or {}).get("title", "—")
        # Pula títulos marcados como cópia/teste (ex: '(copy 01)', '(test)')
        # — são duplicações da régua oficial pra teste interno.
        if any(tag in (title or "").lower() for tag in ("(copy", "(test", " teste")):
            print(f"  [skip] {title}: sent={sent}")
            continue
        send_time = c.get("send_time", "")
        rep = fetch_campaign_report(c["id"]) or {}
        enriched.append({
            "id": c["id"],
            "type": ctype,                   # automation-email | regular
            "subject": subject,
            "title": title,
            "status": c.get("status"),
            "send_time": send_time,
            "month": send_time[:7] if send_time else "",
            **rep,
        })

    print(f"  {len(enriched)} campaigns com envios reais")

    # Agrega por TÍTULO interno (não subject) — title identifica a posição
    # da mensagem na cadência (ex: 'Cadência → Dia 01'), enquanto subject
    # pode se repetir entre emails diferentes (A/B test, variações).
    # Cada execução da régua vira uma campaign — somar dá métrica da etapa.
    by_step = defaultdict(lambda: {
        "n": 0, "sent": 0, "opens_total": 0, "unique_opens": 0,
        "clicks_total": 0, "unique_clicks": 0, "unsubscribed": 0,
        "hard_bounces": 0, "soft_bounces": 0,
        "first_send": "", "last_send": "", "type": "",
        "subject": "",  # subject mais comum dessa etapa
    })
    for c in enriched:
        key = c["title"] or c["subject"] or "—"
        d = by_step[key]
        d["n"] += 1
        for k in ("sent", "opens_total", "unique_opens", "clicks_total",
                  "unique_clicks", "unsubscribed", "hard_bounces", "soft_bounces"):
            d[k] += c.get(k, 0)
        d["type"] = c["type"]
        # Subject: pega o mais recente (ou o primeiro se múltiplos)
        if not d["subject"] or (c.get("send_time","") > (d.get("_last_st","") or "")):
            d["subject"] = c["subject"]
            d["_last_st"] = c.get("send_time","")
        st = c.get("send_time", "")[:10]
        if st:
            if not d["first_send"] or st < d["first_send"]: d["first_send"] = st
            if not d["last_send"]  or st > d["last_send"]:  d["last_send"] = st
    # Limpa chave temporária
    for d in by_step.values():
        d.pop("_last_st", None)

    # Agrega por mês
    by_month = defaultdict(lambda: {
        "sent": 0, "unique_opens": 0, "clicks_total": 0, "unsubscribed": 0
    })
    for c in enriched:
        m = c.get("month", "")
        if not m: continue
        by_month[m]["sent"]         += c["sent"]
        by_month[m]["unique_opens"] += c["unique_opens"]
        by_month[m]["clicks_total"] += c["clicks_total"]
        by_month[m]["unsubscribed"] += c["unsubscribed"]

    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data_center": DC,
        "audience": aud,
        "campaigns": enriched,
        "by_step":    dict(by_step),     # agregado por etapa da cadência (title)
        "by_subject": dict(by_step),     # alias retrocompat — código antigo lia 'by_subject'
        "by_month":   dict(by_month),
    }

    out_path = Path(__file__).resolve().parent / "data/mailchimp.json"
    # Salvaguarda: se voltou vazio mas há JSON antigo, preserva
    if not enriched and out_path.exists():
        print("⚠️  Sem dados novos — mantendo JSON anterior")
        return

    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✅ Salvo em: {out_path}")
    print(f"   Etapas da cadência: {len(by_step)}")
    print(f"   Envios totais: {sum(d['sent'] for d in by_step.values())}")


if __name__ == "__main__":
    main()
