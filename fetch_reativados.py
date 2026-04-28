"""
Relatório one-off: leads SDR + Closer com tag "lead reativado",
agrupados por mês desde janeiro/2026 (ou outro período via env vars).

Saída: stdout (consumido pelo workflow `reativados-report.yml`).
Não salva JSON — é um relatório pontual, não dado contínuo do dashboard.
"""

import os, requests
from datetime import datetime, date
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

SUBDOMAIN = os.environ["KOMMO_SUBDOMAIN"]
TOKEN     = os.environ["KOMMO_TOKEN"]

# Pipelines
PIPELINE_SDR    = 12716679
PIPELINE_CLOSER = 12719415

# Período: desde início do ano até hoje (override via PERIOD_START env)
PERIOD_START = date.fromisoformat(os.environ.get("PERIOD_START", "2026-01-01"))
PERIOD_END   = date.today()

TARGET_TAG = "lead reativado"


def hdrs():
    return {"Authorization": f"Bearer {TOKEN}"}


def kommo_get(path, params=None):
    r = requests.get(f"https://{SUBDOMAIN}.kommo.com{path}", headers=hdrs(), params=params)
    return r.json() if r.ok and r.text else {}


def _period_ts():
    ts_from = int(datetime(PERIOD_START.year, PERIOD_START.month, PERIOD_START.day).timestamp())
    ts_to   = int(datetime(PERIOD_END.year, PERIOD_END.month, PERIOD_END.day, 23, 59, 59).timestamp())
    return ts_from, ts_to


def _paged_leads(params):
    leads, page = [], 1
    while True:
        p = dict(params); p.update({"limit": 250, "page": page, "with": "contacts"})
        data = kommo_get("/api/v4/leads", params=p)
        batch = data.get("_embedded", {}).get("leads", [])
        if not batch: break
        leads.extend(batch)
        if len(batch) < 250: break
        page += 1
    return leads


def get_leads(pipeline_id):
    ts_from, ts_to = _period_ts()
    return _paged_leads({
        "filter[pipeline_id]":      pipeline_id,
        "filter[created_at][from]": ts_from,
        "filter[created_at][to]":   ts_to,
    })


def lead_tags(lead):
    tags = lead.get("_embedded", {}).get("tags", []) or []
    return [(t.get("name") or "").strip().lower() for t in tags]


def main():
    print(f"=== Relatório de Leads Reativados ===")
    print(f"Período: {PERIOD_START} → {PERIOD_END}")
    print(f"Tag alvo: '{TARGET_TAG}'")
    print(f"Pipelines: SDR ({PIPELINE_SDR}) + Closer ({PIPELINE_CLOSER})\n")

    # Busca SDR e Closer (filtro por created_at)
    print("Buscando SDR...")
    sdr_leads = get_leads(PIPELINE_SDR)
    print(f"  {len(sdr_leads)} leads SDR no período\n")

    print("Buscando Closer...")
    closer_leads = get_leads(PIPELINE_CLOSER)
    print(f"  {len(closer_leads)} leads Closer no período\n")

    # Filtrar pela tag e agrupar por mês
    by_month = defaultdict(lambda: {"sdr": 0, "closer": 0, "ids_sdr": [], "ids_closer": []})

    for lead in sdr_leads:
        if TARGET_TAG in lead_tags(lead):
            ts = lead.get("created_at") or 0
            month = datetime.fromtimestamp(ts).strftime("%Y-%m") if ts else "sem-data"
            by_month[month]["sdr"] += 1
            by_month[month]["ids_sdr"].append(lead["id"])

    for lead in closer_leads:
        if TARGET_TAG in lead_tags(lead):
            ts = lead.get("created_at") or 0
            month = datetime.fromtimestamp(ts).strftime("%Y-%m") if ts else "sem-data"
            by_month[month]["closer"] += 1
            by_month[month]["ids_closer"].append(lead["id"])

    # Imprimir tabela
    print("=" * 60)
    print(f"RESULTADO — Leads com tag '{TARGET_TAG}'")
    print("=" * 60)
    print(f"{'Mês':<10} {'SDR':>6} {'Closer':>8} {'Total':>8}")
    print("-" * 40)
    total_sdr = total_closer = 0
    for m in sorted(by_month.keys()):
        sdr = by_month[m]["sdr"]
        cl  = by_month[m]["closer"]
        total_sdr += sdr
        total_closer += cl
        print(f"{m:<10} {sdr:>6} {cl:>8} {sdr+cl:>8}")
    print("-" * 40)
    print(f"{'TOTAL':<10} {total_sdr:>6} {total_closer:>8} {total_sdr+total_closer:>8}")
    print()

    # Detalhamento de IDs
    print("IDs por mês (pra investigação manual no Kommo):")
    for m in sorted(by_month.keys()):
        if by_month[m]["ids_sdr"]:
            print(f"  {m} SDR:    {by_month[m]['ids_sdr']}")
        if by_month[m]["ids_closer"]:
            print(f"  {m} Closer: {by_month[m]['ids_closer']}")


if __name__ == "__main__":
    main()
