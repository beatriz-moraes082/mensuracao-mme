"""
Busca leads do IMR (Ipioca Mar Resort) no Kommo CRM e salva JSON estruturado
para o dashboard dinâmico.

Saída: data/kommo_leads.json
"""

import json, os, requests
from datetime import datetime, date, timezone
from pathlib import Path

def _load_env():
    """Lê .env (formato KEY=VALUE) da raiz do projeto e popula os.environ."""
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

# IMR pipelines
PIPELINE_SDR    = 12716679
PIPELINE_CLOSER = 12719415
PIPELINE_DUQUE  = 12719007

# Lead custom fields
CF_SCORE = 2929964   # Lead score A/B/C/D

# Contact custom fields
CF_ORIGEM      = 3167410  # Origem (Meta Ads / Google+Ads / ...)
CF_CAMPANHA    = 3167412  # Campanha
CF_PUBLICO     = 3167420  # Público (audience/adset)
CF_ANUNCIO     = 3167422  # Anúncio (creative/ad)
CF_PHONE       = 2813078  # Telefone
CF_MEDIUM      = 4226808  # Medium (cpc/organic/...)
CF_HOSPEDAGEM  = 4226162  # Como se hospeda quando viaja
CF_VIAJA_MAIS  = 4226170  # Você costuma viajar mais
CF_INVESTIMENTO= 4226176  # Quanto investe/ano em viagens
CF_INTERESSE_AI= 4226180  # Tem interesse em Resort All-inclusive

# Status stages — real IDs from ipiocamarresort.kommo.com
# SDR pipeline (12716679) — status 142 aqui = "Reunião realizada" (sucesso SDR, NÃO é venda)
SDR_QUALIF  = 98147491   # Lead qualificado
SDR_REUNIAO = 98162603   # Reunião agendada
# Closer pipeline (12719415) — status 142 aqui = venda real
CLO_REALIZ  = 98168239   # Reunião Realizada
CLO_PROP    = 98169055   # Proposta Enviada
CLO_FOLLOW  = 98169059   # Follow-up (Closer)
CLO_VERDE   = 98334563   # Sinal Verde

WON  = 142   # built-in "Venda ganha" (significado varia por pipeline)
LOST = 143   # built-in "Venda perdida"

# Tags (lowercase) que indicam "Reunião Agendada" por regra do cliente
TAGS_REUNIAO = {"reunião-agendada", "reunião-realizada", "reagendar-reunião"}

# Período: desde início da operação (01/04/2026) até hoje.
PERIOD_START = date(2026, 4, 1)
PERIOD_END   = date.today()

def week_of(ts):
    """w1-w4 por dia do mês — genérico (funciona em qualquer mês)."""
    d = datetime.fromtimestamp(ts).date()
    if d.day <= 7:  return "w1"
    if d.day <= 14: return "w2"
    if d.day <= 21: return "w3"
    return "w4"

def month_of(ts):
    """Retorna 'YYYY-MM' do timestamp."""
    d = datetime.fromtimestamp(ts).date()
    return f"{d.year:04d}-{d.month:02d}"

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
        print(f"    pg{page}: {len(batch)} leads")
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

def get_leads_closed(pipeline_id):
    """Leads do pipeline fechados (won/lost) dentro do período — filtro por closed_at."""
    ts_from, ts_to = _period_ts()
    return _paged_leads({
        "filter[pipeline_id]":     pipeline_id,
        "filter[closed_at][from]": ts_from,
        "filter[closed_at][to]":   ts_to,
    })

def get_contacts_map(contact_ids):
    result = {}
    ids = list(set(contact_ids))
    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        params = {"limit": 250}
        for j, cid in enumerate(batch):
            params[f"filter[id][{j}]"] = cid
        data = kommo_get("/api/v4/contacts", params=params)
        for c in data.get("_embedded", {}).get("contacts", []):
            cf_map = {}
            for cf in (c.get("custom_fields_values") or []):
                vals = cf.get("values") or []
                # phone is multitext — grab first
                val = str(vals[0].get("value", "")) if vals else ""
                if val:
                    cf_map[cf["field_id"]] = val
            result[c["id"]] = cf_map
    return result

def lead_contact_id(lead):
    cs = lead.get("_embedded", {}).get("contacts", [])
    return cs[0]["id"] if cs else 0

def get_lead_cf(lead, field_id):
    for cf in (lead.get("custom_fields_values") or []):
        if cf["field_id"] == field_id:
            vals = cf.get("values") or []
            return str(vals[0]["value"]) if vals else ""
    return ""

def get_lead_tags(lead):
    """Retorna lista de nomes de tags (lowercase, sem espaço extra)."""
    tags = lead.get("_embedded", {}).get("tags", []) or []
    return [ (t.get("name") or "").strip().lower() for t in tags ]

def classify(pipeline, status, tags, closed_in_period):
    """Regras do cliente (abril/2026):
      - SDR:
         qualified = status em {Lead Qualificado, Reunião Agendada, Reunião Realizada}
                     OU tem tag de reunião (reunião-agendada/realizada/reagendar)
                     — leads que agendaram/realizaram reunião passaram pela qualificação
         reuniao_agendada = qualquer tag em TAGS_REUNIAO
         reuniao_realizada = status 142 no SDR
      - Closer:
         proposta = Proposta Enviada + Follow-up + Sinal Verde
         venda    = status 142 no Closer E fechado no período (closed_at)
    """
    qualified = reuniao_agendada = reuniao_realizada = proposta = venda = False
    tag_set = set(tags)
    if pipeline == PIPELINE_SDR:
        reuniao_agendada  = bool(tag_set & TAGS_REUNIAO)
        # Reunião realizada: status 142 OU tem tag "reunião-realizada"
        # (lead pode estar em outro status após a reunião — ex: Follow-up pós-meeting)
        reuniao_realizada = (status == WON) or ("reunião-realizada" in tag_set)
        # Qualificado = está numa etapa qualificada OU já passou pela reunião (tags)
        qualified = (status in {SDR_QUALIF, SDR_REUNIAO, WON}) or reuniao_agendada
    elif pipeline == PIPELINE_CLOSER:
        proposta = status in {CLO_PROP, CLO_FOLLOW, CLO_VERDE}
        venda    = (status == WON) and closed_in_period
    return qualified, reuniao_agendada, reuniao_realizada, proposta, venda

def process_lead(lead, contacts_map):
    cid       = lead_contact_id(lead)
    contact   = contacts_map.get(cid, {})
    status    = lead.get("status_id", 0)
    pipeline  = lead.get("pipeline_id", 0)
    ts        = lead.get("created_at", 0)
    closed_at = lead.get("closed_at", 0) or 0
    ts_from, ts_to = _period_ts()
    closed_in_period = bool(closed_at and ts_from <= closed_at <= ts_to)
    raw_phone = contact.get(CF_PHONE, "").replace("+","").replace(" ","").replace("-","")
    # Mascarar telefone pra publicação pública — mantém só últimos 4 dígitos
    # (phone_hash preserva dedup por contato sem expor o número)
    phone_hash = raw_phone[-10:] if raw_phone else ""  # só usado internamente pra dedup
    phone_masked = (raw_phone[:2] + "X"*(len(raw_phone)-6) + raw_phone[-4:]) if len(raw_phone) >= 10 else ""
    tags  = get_lead_tags(lead)
    qualified, reuniao_agendada, reuniao_realizada, proposta, venda = classify(pipeline, status, tags, closed_in_period)

    return {
        "id":        lead["id"],
        "created_at": ts,
        "closed_at":  closed_at,
        "closed_in_period": closed_in_period,
        "week":      week_of(ts) if ts else "w4",
        "month":     month_of(ts) if ts else "2026-04",
        "status":    status,
        "pipeline":  pipeline,
        "loss_reason_id": lead.get("loss_reason_id") or 0,
        "price":     lead.get("price", 0) or 0,
        "score":      get_lead_cf(lead, CF_SCORE),
        "origem":     contact.get(CF_ORIGEM, ""),       # "Meta Ads" / "Google+Ads" / ""
        "audience":   contact.get(CF_PUBLICO, ""),
        "creative":   contact.get(CF_ANUNCIO, ""),
        "campaign":   contact.get(CF_CAMPANHA, ""),
        "medium":     contact.get(CF_MEDIUM, ""),
        "phone":      phone_masked,   # telefone mascarado (55XXXXXXXX1234) pra publicação
        "_phone_key": phone_hash,     # usado apenas em memória pra deduplicar; removido antes de salvar
        "tags":       tags,
        "hospedagem": contact.get(CF_HOSPEDAGEM, ""),
        "viaja_mais": contact.get(CF_VIAJA_MAIS, ""),
        "investimento":contact.get(CF_INVESTIMENTO, ""),
        "interesse_ai":contact.get(CF_INTERESSE_AI, ""),
        "qualified":         qualified,
        "reuniao_agendada":  reuniao_agendada,
        "reuniao_realizada": reuniao_realizada,
        "proposta":          proposta,
        "venda":             venda,
        "perda":             status == LOST,
    }

def get_pipeline_statuses():
    """Fetch real status IDs for all IMR pipelines."""
    status_map = {}
    for pid in [PIPELINE_SDR, PIPELINE_CLOSER, PIPELINE_DUQUE]:
        data = kommo_get(f"/api/v4/leads/pipelines/{pid}")
        for st in data.get("_embedded", {}).get("statuses", []):
            status_map[st["id"]] = st["name"]
    return status_map

def get_loss_reasons():
    """Busca mapeamento de loss_reason_id → nome."""
    reasons = {}
    page = 1
    while True:
        data = kommo_get("/api/v4/leads/loss_reasons", params={"limit": 250, "page": page})
        batch = data.get("_embedded", {}).get("loss_reasons", []) if data else []
        if not batch: break
        for lr in batch: reasons[lr["id"]] = lr.get("name", "")
        if len(batch) < 250: break
        page += 1
    return reasons

def main():
    print(f"\n{'='*60}")
    print("  Kommo IMR → dashboard-imr/data/kommo_leads.json")
    print(f"  Período: {PERIOD_START} → {PERIOD_END}")
    print(f"{'='*60}\n")

    # Get real status names
    print("📋 Buscando status dos pipelines...")
    status_map = get_pipeline_statuses()
    for sid, name in status_map.items():
        print(f"  status {sid}: {name}")

    print("\n📋 Buscando motivos de perda...")
    loss_reasons_map = get_loss_reasons()
    print(f"  {len(loss_reasons_map)} motivos encontrados")

    # Fetch pipelines (created_at in period)
    print("\n📋 Buscando leads SDR (created_at)...")
    leads_sdr = get_leads(PIPELINE_SDR)
    print(f"  Total SDR: {len(leads_sdr)}")

    print("📋 Buscando leads Closer (created_at)...")
    leads_closer = get_leads(PIPELINE_CLOSER)
    print(f"  Total Closer (criados): {len(leads_closer)}")

    print("📋 Buscando leads Closer fechados (closed_at)...")
    leads_closer_closed = get_leads_closed(PIPELINE_CLOSER)
    print(f"  Total Closer (fechados): {len(leads_closer_closed)}")

    # Merge Closer (dedup by id)
    seen_ids = set()
    leads_closer_all = []
    for l in leads_closer + leads_closer_closed:
        if l["id"] in seen_ids: continue
        seen_ids.add(l["id"])
        leads_closer_all.append(l)
    print(f"  Total Closer (merge): {len(leads_closer_all)}")

    print("📋 Buscando leads Duque...")
    leads_duque = get_leads(PIPELINE_DUQUE)
    print(f"  Total Duque: {len(leads_duque)}")

    all_leads = leads_sdr + leads_closer_all + leads_duque

    # Fetch contacts
    contact_ids = [lead_contact_id(l) for l in all_leads if lead_contact_id(l)]
    print(f"\n👥 Buscando {len(set(contact_ids))} contatos...")
    contacts_map = get_contacts_map(contact_ids)

    # Process
    processed_sdr    = [process_lead(l, contacts_map) for l in leads_sdr]
    processed_closer = [process_lead(l, contacts_map) for l in leads_closer_all]
    processed_duque  = [process_lead(l, contacts_map) for l in leads_duque]

    # Deduplicate SDR by phone (usa _phone_key não mascarado; removido depois)
    seen_phones, deduped_sdr = set(), []
    for l in processed_sdr:
        p = l.get("_phone_key", "")
        if p and len(p) >= 10:
            if p in seen_phones: continue
            seen_phones.add(p)
        deduped_sdr.append(l)
    # Remove chave interna antes de salvar (não pode ir pro JSON público)
    for lst in (deduped_sdr, processed_closer, processed_duque):
        for l in lst:
            l.pop("_phone_key", None)
    print(f"\n  SDR bruto: {len(processed_sdr)} → deduplicado: {len(deduped_sdr)}")

    from collections import Counter
    scores = Counter(l["score"] for l in deduped_sdr if l["score"])
    print(f"  Scores: {dict(scores)}")
    audiences = Counter(l["audience"] for l in deduped_sdr if l["audience"])
    print(f"  Top públicos: {dict(audiences.most_common(5))}")

    # Dedup vendas: mesmo contato fechado na mesma data = 1 venda só
    # (corrige duplicações manuais no Kommo)
    # Buscamos contact_id original de cada closer lead vendido
    closer_id_to_contact = {}
    for l in leads_closer_all:
        cid = lead_contact_id(l)
        closer_id_to_contact[l["id"]] = cid
    seen_venda_keys = set()
    venda_dups = 0
    for l in processed_closer:
        if not l["venda"]: continue
        cid = closer_id_to_contact.get(l["id"], 0)
        from datetime import datetime as _dt
        closed_day = _dt.fromtimestamp(l["closed_at"]).strftime("%Y-%m-%d") if l["closed_at"] else ""
        key = (cid, closed_day)
        if cid and key in seen_venda_keys:
            l["venda"] = False
            l["duplicated"] = True
            venda_dups += 1
        else:
            seen_venda_keys.add(key)
            l["duplicated"] = False
    if venda_dups:
        print(f"\n⚠️  {venda_dups} venda(s) duplicada(s) removida(s) (mesmo contato + mesma data de fechamento)")

    # Métricas agregadas (regras do cliente)
    total_leads       = len(deduped_sdr) + len(processed_duque)
    total_qualificado = sum(1 for l in deduped_sdr if l["qualified"])
    total_reu_agend   = sum(1 for l in deduped_sdr if l["reuniao_agendada"])
    total_reu_real    = sum(1 for l in deduped_sdr if l["reuniao_realizada"])
    total_proposta    = sum(1 for l in processed_closer if l["proposta"])
    total_venda       = sum(1 for l in processed_closer if l["venda"])
    total_receita     = sum(l["price"] for l in processed_closer if l["venda"])
    total_perda       = (sum(1 for l in deduped_sdr if l["perda"]) +
                         sum(1 for l in processed_closer if l["perda"] and l["closed_in_period"]) +
                         sum(1 for l in processed_duque if l["perda"]))

    metrics = {
        "leads":             total_leads,
        "qualified":         total_qualificado,
        "reuniao_agendada":  total_reu_agend,
        "reuniao_realizada": total_reu_real,
        "proposta":          total_proposta,
        "venda":             total_venda,
        "receita":           total_receita,
        "perda":             total_perda,
        "vendas_duplicadas_removidas": venda_dups,
    }
    print(f"\n📊 MÉTRICAS (regras do cliente):")
    for k,v in metrics.items(): print(f"  {k:20s}: {v}")

    output = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "period":     {"start": str(PERIOD_START), "end": str(PERIOD_END)},
        "status_map": {str(k): v for k, v in status_map.items()},
        "loss_reasons": {str(k): v for k, v in loss_reasons_map.items()},
        "metrics":    metrics,
        "sdr":    deduped_sdr,
        "closer": processed_closer,
        "duque":  processed_duque,
    }

    out_path = Path(__file__).resolve().parent / "data/kommo_leads.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n✅ Salvo em: {out_path}")
    print(f"   SDR: {len(deduped_sdr)} | Closer: {len(processed_closer)} | Duque: {len(processed_duque)}")

if __name__ == "__main__":
    main()
