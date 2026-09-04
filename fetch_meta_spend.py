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

# Conta do Instagram usada pra métricas de visibilidade de marca (@mmevacationclub).
# É a conta que os anúncios do IMR publicam; achada via act_.../connected_instagram_accounts.
# Override por env IG_ACCOUNT se um dia mudar.
IG_ACCOUNT = os.environ.get("IG_ACCOUNT", "17841472519672614")

# Tipos de ação (actions) do Meta que representam engajamento de visibilidade.
ACT_SHARE   = 'post'                          # compartilhamentos
ACT_SAVE    = 'onsite_conversion.post_save'   # salvamentos
ACT_COMMENT = 'comment'                        # comentários

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

def fetch_visibility():
    """Métricas de visibilidade de marca, granularidade DIÁRIA (pra somar em qualquer
    período do dashboard). Duas fontes:
      • Anúncios (account insights, campo `actions`): compartilhamentos, salvamentos, comentários + spend.
      • Instagram @mmevacationclub (IG Graph): visitas ao perfil (profile_views) e novos seguidores (follower_count).
    Retorna {'YYYY-MM-DD': {spend, profile_views, followers, shares, saves, comments}}.
    Cada bloco é isolado por try/except: se o IG falhar, ainda volta os dados de anúncio."""
    from datetime import timedelta
    daily = defaultdict(lambda: {'spend':0.0,'profile_views':0,'followers':0,
                                 'shares':0,'saves':0,'comments':0})
    start = datetime.fromisoformat(SINCE).date()
    end   = datetime.fromisoformat(UNTIL).date()

    # ── 1) Anúncios: spend + actions por dia (nível CAMPANHA) ──────────────────
    # GASTO conta APENAS campanhas de topo de funil (nome contém "Topo de Funil")
    # — é o investimento em visibilidade/branding, não os leads (fundo de funil).
    # Engajamento (compart./salv./coment.) segue contando todas as campanhas.
    print('  [vis] campaign insights (spend topo-de-funil + actions)...')
    for since, until in _month_chunks(SINCE, UNTIL):
        url = f'https://graph.facebook.com/v21.0/{ACCOUNT}/insights'
        params = {'access_token':TOKEN,'level':'campaign','fields':'campaign_name,spend,actions',
                  'time_increment':1,'limit':500,
                  'time_range':f'{{"since":"{since}","until":"{until}"}}'}
        while url:
            r = requests.get(url, params=params); d = r.json()
            if 'error' in d:
                print(f'    ❌ campaign {since}→{until}: {d["error"].get("message")}'); break
            for row in d.get('data', []):
                ds = row.get('date_start')
                if not ds: continue
                is_top = 'topo de funil' in (row.get('campaign_name') or '').lower()
                if is_top:
                    daily[ds]['spend'] += float(row.get('spend', 0))
                for a in row.get('actions', []):
                    t, v = a.get('action_type'), int(float(a.get('value', 0)))
                    if   t == ACT_SHARE:   daily[ds]['shares']   += v
                    elif t == ACT_SAVE:    daily[ds]['saves']    += v
                    elif t == ACT_COMMENT: daily[ds]['comments'] += v
            url = d.get('paging', {}).get('next'); params = {}

    # ── 2) Instagram: novos seguidores por dia (follower_count) ────────────────
    # Limite do Meta: follower_count só cobre os ÚLTIMOS 30 DIAS (excluindo hoje).
    # Histórico mais antigo é inacessível — por isso o main() mescla com o JSON
    # anterior pra preservar os dias que já saíram dessa janela.
    print(f'  [vis] IG follower_count (id={IG_ACCOUNT}, janela de 30d)...')
    fc_start = max(start, end - timedelta(days=30))
    fc_end   = end - timedelta(days=1)   # dia corrente não é suportado
    if fc_end >= fc_start:
        r = requests.get(f'https://graph.facebook.com/v21.0/{IG_ACCOUNT}/insights',
                         params={'access_token':TOKEN,'metric':'follower_count','period':'day',
                                 'since':fc_start.isoformat(),'until':(fc_end+timedelta(days=1)).isoformat()}).json()
        if 'error' in r:
            print(f'    ⚠️  follower_count: {r["error"].get("message")}')
        for m in r.get('data', []):
            for val in m.get('values', []):
                ds = (val.get('end_time') or '')[:10]
                if ds: daily[ds]['followers'] += int(val.get('value') or 0)

    # ── 3) Instagram: visitas ao perfil por dia (profile_views, janelas de 1 dia) ─
    # profile_views só sai como total_value de um intervalo — não tem array por dia —
    # então puxamos dia a dia. Erro num dia não derruba o resto.
    print('  [vis] IG profile_views (dia a dia)...')
    pv_ok = pv_err = 0
    d = start
    while d <= end:
        try:
            r = requests.get(f'https://graph.facebook.com/v21.0/{IG_ACCOUNT}/insights',
                             params={'access_token':TOKEN,'metric':'profile_views','period':'day',
                                     'metric_type':'total_value',
                                     'since':d.isoformat(),'until':(d+timedelta(days=1)).isoformat()},
                             timeout=15).json()
            data = r.get('data', [])
            if data:
                daily[d.isoformat()]['profile_views'] += int(data[0].get('total_value', {}).get('value') or 0)
                pv_ok += 1
            elif 'error' in r:
                pv_err += 1
        except Exception:
            pv_err += 1
        d += timedelta(days=1)
    print(f'    profile_views: {pv_ok} dias ok, {pv_err} sem dado/erro')

    return {k: {'spend':round(v['spend'],2),'profile_views':v['profile_views'],
                'followers':v['followers'],'shares':v['shares'],
                'saves':v['saves'],'comments':v['comments']}
            for k, v in sorted(daily.items())}


def fetch_top_content():
    """Posts do Instagram @mmevacationclub (desde SINCE) com métricas de engajamento,
    pra ranquear os 'top conteúdos'. Retorna lista de dicts com preview (thumbnail +
    permalink). Os thumbnails do IG são URLs de CDN que expiram — como o cron re-roda
    diariamente, ficam sempre frescos; o permalink nunca expira."""
    from datetime import timedelta
    G = 'https://graph.facebook.com/v21.0'
    fields = ('id,caption,media_type,media_product_type,media_url,thumbnail_url,'
              'permalink,timestamp,like_count,comments_count')
    posts, url = [], f'{G}/{IG_ACCOUNT}/media'
    params = {'access_token':TOKEN,'limit':50,'fields':fields}
    stop = False
    while url and not stop and len(posts) < 120:
        d = requests.get(url, params=params).json()
        if 'error' in d:
            print(f'    ⚠️  media: {d["error"].get("message")}'); break
        for m in d.get('data', []):
            if (m.get('timestamp','') or '')[:10] < SINCE:
                stop = True; break
            posts.append(m)
        if stop: break
        url = d.get('paging', {}).get('next'); params = {}

    def _insights(mid):
        for mset in ('reach,saved,shares,total_interactions,views','reach,saved,total_interactions'):
            r = requests.get(f'{G}/{mid}/insights', params={'access_token':TOKEN,'metric':mset}).json()
            if 'error' not in r:
                return {x['name']: (x.get('values',[{}])[0].get('value') or 0) for x in r.get('data',[])}
        return {}

    out = []
    for m in posts:
        ins = _insights(m['id'])
        cap = (m.get('caption') or '').replace('\n',' ').strip()
        out.append({
            'id':        m['id'],
            'permalink': m.get('permalink',''),
            'thumb':     m.get('thumbnail_url') or m.get('media_url') or '',
            'type':      m.get('media_product_type') or m.get('media_type') or '',
            'date':      (m.get('timestamp','') or '')[:10],
            'caption':   cap[:120],
            'reach':        int(ins.get('reach',0) or 0),
            'views':        int(ins.get('views',0) or 0),
            'saved':        int(ins.get('saved',0) or 0),
            'shares':       int(ins.get('shares',0) or 0),
            'comments':     int(m.get('comments_count',0) or 0),
            'likes':        int(m.get('like_count',0) or 0),
            'interactions': int(ins.get('total_interactions',0) or 0),
        })
    out.sort(key=lambda x: -x['interactions'])
    return out


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

    # ── Visibilidade de marca (engajamento anúncios + IG @mmevacationclub) ──────
    print('\nFetching brand visibility metrics...')
    try:
        visibility_daily = fetch_visibility()
        print(f'  {len(visibility_daily)} dias com dados de visibilidade')
    except Exception as e:
        print(f'  ⚠️  visibilidade falhou ({e}); mantém bloco anterior se existir')
        visibility_daily = None

    print('Fetching top content (Instagram)...')
    try:
        top_content = fetch_top_content()
        print(f'  {len(top_content)} posts coletados')
    except Exception as e:
        print(f'  ⚠️  top content falhou ({e})')
        top_content = None

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

    # Visibilidade: se o fetch falhou, preserva o bloco do JSON anterior (não zera a aba).
    prev_path = Path(__file__).resolve().parent / 'data/meta_spend.json'
    prev_daily = {}
    if prev_path.exists():
        try:
            prev_daily = (json.loads(prev_path.read_text()).get('visibility') or {}).get('daily') or {}
        except Exception:
            prev_daily = {}

    if visibility_daily is not None:
        # Merge: 'follower_count' do Meta só cobre ~30 dias. Pros dias que já saíram
        # dessa janela (fetch novo traz followers=0), mantém o valor já capturado antes,
        # senão o histórico de seguidores encolheria a cada rodada do cron.
        for ds, prev in prev_daily.items():
            if prev.get('followers', 0) and not visibility_daily.get(ds, {}).get('followers', 0):
                visibility_daily.setdefault(ds, {'spend':0.0,'profile_views':0,'followers':0,
                                                 'shares':0,'saves':0,'comments':0})
                visibility_daily[ds]['followers'] = prev['followers']
        out['visibility'] = {
            'ig_account': 'mmevacationclub',
            'ig_id':      IG_ACCOUNT,
            'daily':      dict(sorted(visibility_daily.items())),
        }
    elif prev_daily:
        out['visibility'] = {'ig_account':'mmevacationclub','ig_id':IG_ACCOUNT,'daily':prev_daily}

    # Top conteúdos: usa o fetch novo; se falhou, preserva o do JSON anterior.
    if out.get('visibility') is not None:
        if top_content is not None:
            out['visibility']['top_content'] = top_content
        else:
            prev_tc = []
            if prev_path.exists():
                try:
                    prev_tc = (json.loads(prev_path.read_text()).get('visibility') or {}).get('top_content') or []
                except Exception:
                    prev_tc = []
            if prev_tc: out['visibility']['top_content'] = prev_tc

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
