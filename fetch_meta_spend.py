"""
Busca gasto Meta Ads por adset (público) e por anúncio (criativo) — semanal.
Saída: data/meta_spend.json
"""

import json, os, requests
from datetime import date
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
SINCE   = '2026-04-01'
UNTIL   = '2026-04-30'

WEEK_MAP = {
    '2026-04-01': 'w1',
    '2026-04-08': 'w2',
    '2026-04-15': 'w3',
    '2026-04-22': 'w4',
}

def week_of(date_str):
    return WEEK_MAP.get(date_str[:10], 'w4')

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
    while url:
        r = requests.get(url, params=params)
        data = r.json()
        if 'error' in data:
            print(f'  Error: {data["error"]["message"]}')
            break
        rows.extend(data.get('data', []))
        url    = data.get('paging', {}).get('next')
        params = {}   # next page URL already has all params
    return rows

def main():
    print('=== Meta Ads Spend Fetch ===')

    # ── Adset level ───────────────────────────────────────────────────────────
    print('Fetching adset insights...')
    adset_rows = fetch_insights('adset')
    adset_spend = defaultdict(lambda: defaultdict(float))  # {adset_name: {week: spend}}
    for row in adset_rows:
        name  = normalize_adset(row.get('adset_name', '—'))
        spend = float(row.get('spend', 0))
        week  = week_of(row.get('date_start', ''))
        adset_spend[name][week] += spend
    print(f'  {len(adset_spend)} adsets')
    for name, wks in adset_spend.items():
        total = sum(wks.values())
        print(f'  {name[:50]} → R${total:.2f}')

    # ── Ad (creative) level ────────────────────────────────────────────────────
    print('\nFetching ad insights...')
    ad_rows = fetch_insights('ad')
    cri_spend = defaultdict(lambda: defaultdict(float))    # {creative_name: {week: spend}}
    for row in ad_rows:
        name  = normalize_creative(row.get('ad_name', '—'))
        spend = float(row.get('spend', 0))
        week  = week_of(row.get('date_start', ''))
        cri_spend[name][week] += spend
    print(f'  {len(cri_spend)} creatives (normalized)')
    for name, wks in cri_spend.items():
        total = sum(wks.values())
        print(f'  {name} → R${total:.2f}')

    # ── Build output ───────────────────────────────────────────────────────────
    out = {
        'fetched_at': date.today().isoformat(),
        'period':     {'since': SINCE, 'until': UNTIL},
        'adset':      {k: dict(v) for k, v in adset_spend.items()},
        'creative':   {k: dict(v) for k, v in cri_spend.items()},
    }

    out_path = Path(__file__).resolve().parent / 'data/meta_spend.json'
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f'\n✅ Salvo em: {out_path}')

if __name__ == '__main__':
    main()
