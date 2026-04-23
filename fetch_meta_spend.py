"""
Busca gasto Meta Ads por adset (público) e por anúncio (criativo) — semanal.
Saída: data/meta_spend.json
"""

import json, os, requests
from datetime import date, datetime, timezone
from collections import defaultdict
from pathlib import Path

def _load_env():
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists(): return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_env()

TOKEN   = os.environ["META_TOKEN"]
ACCOUNT = os.environ["META_ACCOUNT"]

# Período: desde início da operação (01/04/2026) até hoje.
SINCE   = '2026-04-01'
UNTIL   = date.today().isoformat()

def week_of(date_str):
    """Bucket w1-w4 por dia do mês — alinhado com a lógica do dashboard."""
    if not date_str: return 'w4'
    day = int(date_str[8:10])
    if day <= 7:  return 'w1'
    if day <= 14: return 'w2'
    if day <= 21: return 'w3'
    return 'w4'

def month_of(date_str):
    """Retorna 'YYYY-MM' a partir de 'YYYY-MM-DD'."""
    return date_str[:7] if date_str else '2026-04'

def normalize_creative(name):
    """Normalise creative names: 'VD02', 'BN01 | Ana' → 'BN01', etc."""
    if not name: return '—'
    # Strip ' | Ana', ' | X' suffixes
    parts = name.split(' | ')
    base = parts[0].strip()
    return base

def normalize_adset(name):
    """Remove asteriscos e espaços extras pra casar com Kommo."""
    if not name: return '—'
    return name.replace('*', '').strip()

def fetch_insights(level):
    rows, url = [], f'https://graph.facebook.com/v21.0/{ACCOUNT}/insights'
    params = {
        'access_token': TOKEN,
        'level':         level,
        'fields':        f'{level}_name,spend,impressions,clicks',
        'time_range':    f'{{"since":"{SINCE}","until":"{UNTIL}"}}',
        'time_increment': 7,
        'limit':         500,
    }
    print(f'  GET {url}')
    print(f'  account={ACCOUNT} token=***{TOKEN[-6:]} level={level} since={SINCE} until={UNTIL}')
    while url:
        r = requests.get(url, params=params)
        print(f'  HTTP {r.status_code}')
        data = r.json()
        if 'error' in data:
            err = data['error']
            print(f'  ❌ ERROR: code={err.get("code")} type={err.get("type")} subcode={err.get("error_subcode")}')
            print(f'     message: {err.get("message")}')
            print(f'     fbtrace_id: {err.get("fbtrace_id")}')
            break
        batch = data.get('data', [])
        rows.extend(batch)
        print(f'  batch: {len(batch)} rows (total {len(rows)})')
        url    = data.get('paging', {}).get('next')
        params = {}   # next page URL already has all params
    return rows

def main():
    print('=== Meta Ads Spend Fetch ===')

    # ── Adset level ───────────────────────────────────────────────────────────
    print('Fetching adset insights...')
    adset_rows = fetch_insights('adset')
    # {adset_name: {month: {week: spend}}}
    adset_spend = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for row in adset_rows:
        name  = normalize_adset(row.get('adset_name', '—'))
        spend = float(row.get('spend', 0))
        ds    = row.get('date_start', '')
        adset_spend[name][month_of(ds)][week_of(ds)] += spend
    print(f'  {len(adset_spend)} adsets')
    for name, months in adset_spend.items():
        total = sum(s for m in months.values() for s in m.values())
        print(f'  {name[:50]} → R${total:.2f}')

    # ── Ad (creative) level ────────────────────────────────────────────────────
    print('\nFetching ad insights...')
    ad_rows = fetch_insights('ad')
    # {creative_name: {month: {week: spend}}}
    cri_spend = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for row in ad_rows:
        name  = normalize_creative(row.get('ad_name', '—'))
        spend = float(row.get('spend', 0))
        ds    = row.get('date_start', '')
        cri_spend[name][month_of(ds)][week_of(ds)] += spend
    print(f'  {len(cri_spend)} creatives (normalized)')
    for name, months in cri_spend.items():
        total = sum(s for m in months.values() for s in m.values())
        print(f'  {name} → R${total:.2f}')

    # Converte defaultdict → dict normal
    def _unwrap(d):
        return {k: {m: dict(wks) for m, wks in months.items()} for k, months in d.items()}

    # ── Build output ───────────────────────────────────────────────────────────
    out = {
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'period':     {'since': SINCE, 'until': UNTIL},
        'adset':      _unwrap(adset_spend),
        'creative':   _unwrap(cri_spend),
    }

    out_path = Path(__file__).resolve().parent / 'data/meta_spend.json'
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f'\n✅ Salvo em: {out_path}')

if __name__ == '__main__':
    main()
