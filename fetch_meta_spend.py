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

def fetch_status(endpoint, name_field, extra_fields=''):
    """Busca effective_status de cada adset/ad (ACTIVE, PAUSED, ARCHIVED, etc.).
    Aceita extra_fields (ex: 'preview_shareable_link' pros ads)."""
    rows, url = [], f'https://graph.facebook.com/v21.0/{ACCOUNT}/{endpoint}'
    fields = f'{name_field},effective_status,status'
    if extra_fields:
        fields = f'{fields},{extra_fields}'
    params = {
        'access_token': TOKEN,
        'fields':       fields,
        'limit':        500,
    }
    print(f'  GET {url} (status)')
    while url:
        r = requests.get(url, params=params)
        data = r.json()
        if 'error' in data:
            err = data['error']
            print(f'  ❌ ERROR status: {err.get("message")}')
            break
        rows.extend(data.get('data', []))
        url    = data.get('paging', {}).get('next')
        params = {}
    return rows

def _month_chunks(since_str, until_str):
    """Divide o período em janelas mensais (início→fim de cada mês, cortando pelo período total).
    Contorna bug do Meta API (#2642 Invalid cursors) que aparece em paginação de períodos longos."""
    from datetime import datetime, timedelta
    start = datetime.fromisoformat(since_str).date()
    end   = datetime.fromisoformat(until_str).date()
    chunks = []
    cur = start
    while cur <= end:
        # Último dia do mês corrente
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        month_end = next_month - timedelta(days=1)
        chunk_end = min(month_end, end)
        chunks.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return chunks

def _fetch_insights_window(level, since, until):
    """Fetch insights de uma janela específica (usado como chunk mensal pra evitar erro de paginação)."""
    rows, url = [], f'https://graph.facebook.com/v21.0/{ACCOUNT}/insights'
    params = {
        'access_token': TOKEN,
        'level':         level,
        'fields':        f'{level}_name,spend,impressions,clicks',
        'time_range':    f'{{"since":"{since}","until":"{until}"}}',
        'time_increment': 1,
        'limit':         500,
    }
    while url:
        r = requests.get(url, params=params)
        data = r.json()
        if 'error' in data:
            err = data['error']
            print(f'  ❌ ERROR window {since}→{until}: code={err.get("code")} · {err.get("message")}')
            break
        batch = data.get('data', [])
        rows.extend(batch)
        url    = data.get('paging', {}).get('next')
        params = {}
    return rows

def fetch_insights(level):
    """Puxa insights dividindo o período em janelas mensais.
    Contorna bug #2642 (Invalid cursors) que aparece em paginação de períodos longos."""
    print(f'  account={ACCOUNT} token=***{TOKEN[-6:]} level={level} since={SINCE} until={UNTIL}')
    all_rows = []
    for since, until in _month_chunks(SINCE, UNTIL):
        chunk_rows = _fetch_insights_window(level, since, until)
        all_rows.extend(chunk_rows)
        print(f'  window {since}→{until}: {len(chunk_rows)} rows (acumulado {len(all_rows)})')
    return all_rows

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

    # ── Status (ACTIVE / PAUSED / etc) ─────────────────────────────────────────
    # Se há múltiplas entidades com o mesmo nome normalizado, considera ACTIVE
    # se PELO MENOS UMA estiver ACTIVE.
    print('\nFetching adset status...')
    adset_status_rows = fetch_status('adsets', 'name')
    print(f'  {len(adset_status_rows)} adsets')
    adset_status = {}
    for row in adset_status_rows:
        name = normalize_adset(row.get('name', ''))
        st   = row.get('effective_status', 'UNKNOWN')
        if name not in adset_status or st == 'ACTIVE':
            adset_status[name] = st

    print('Fetching ad status + preview links...')
    ad_status_rows = fetch_status('ads', 'name', extra_fields='preview_shareable_link,id')
    print(f'  {len(ad_status_rows)} ads')
    cri_status = {}
    cri_preview = {}         # creative_name → link fb.me (fallback pra "abrir no FB")
    cri_preview_iframe = {}  # creative_name → URL do iframe embedável (usada no modal)
    ad_id_by_name = {}       # pra buscar iframe do ad ACTIVE preferencialmente

    def _fetch_iframe_src(ad_id):
        """Chama /previews e extrai o src do iframe (embedável no dashboard)."""
        import re as _re
        url = f'https://graph.facebook.com/v21.0/{ad_id}/previews'
        params = {'access_token': TOKEN, 'ad_format': 'DESKTOP_FEED_STANDARD'}
        try:
            r = requests.get(url, params=params, timeout=10)
            body = r.json().get('data', [{}])[0].get('body', '') if r.ok else ''
            m = _re.search(r'src=[\'"]([^\'"]+)[\'"]', body)
            return m.group(1).replace('&amp;', '&') if m else ''
        except Exception:
            return ''

    for row in ad_status_rows:
        name = normalize_creative(row.get('name', ''))
        st   = row.get('effective_status', 'UNKNOWN')
        prv  = row.get('preview_shareable_link', '')
        aid  = row.get('id', '')
        # Guarda status (prioriza ACTIVE) + link + ID (pra buscar iframe depois)
        if name not in cri_status or st == 'ACTIVE':
            cri_status[name] = st
            if prv: cri_preview[name] = prv
            if aid: ad_id_by_name[name] = aid
        elif name not in cri_preview and prv:
            cri_preview[name] = prv
            if aid and name not in ad_id_by_name: ad_id_by_name[name] = aid

    # Busca iframe URL pra cada creative (só o ad ACTIVE preferido)
    print(f'Fetching preview iframes for {len(ad_id_by_name)} unique creatives...')
    for name, aid in ad_id_by_name.items():
        iframe = _fetch_iframe_src(aid)
        if iframe:
            cri_preview_iframe[name] = iframe
    print(f'  {len(cri_preview_iframe)} iframes coletados')

    # ── Build output ───────────────────────────────────────────────────────────
    out = {
        'fetched_at':     datetime.now(timezone.utc).isoformat(),
        'period':         {'since': SINCE, 'until': UNTIL},
        'adset':          _unwrap(adset_spend),
        'creative':       _unwrap(cri_spend),
        'adset_status':   adset_status,
        'creative_status':cri_status,
        'creative_preview': cri_preview,   # {nome → URL fb.me (abre no FB)}
        'creative_preview_iframe': cri_preview_iframe,  # {nome → URL iframe embedável}
    }

    # Salvaguarda: se a API falhou (token expirado etc) e voltou tudo vazio,
    # NÃO sobrescreve o JSON existente — preserva os dados anteriores.
    out_path = Path(__file__).resolve().parent / 'data/meta_spend.json'
    if not adset_spend and not cri_spend and out_path.exists():
        print('\n⚠️  API retornou vazio (token expirado?). Mantendo dados anteriores.')
        return

    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f'\n✅ Salvo em: {out_path}')

if __name__ == '__main__':
    main()
