#!/usr/bin/env python3
"""
Aplica a tag `Interagiu` nos leads que o SDR realmente resgatou.

Definição de resgate (fechada com a Bia em 2026-09-22):
    houve mensagem ENVIADA POR UM HUMANO para o lead, e depois dela o lead
    respondeu ao menos uma mensagem.

É isso que separa resgate de engajamento espontâneo. A regra que roda hoje no
Kommo ("mensagem recebida em qualquer canal", na etapa Qualificação) marca
qualquer resposta, mesmo sem ninguém ter falado com o lead — medido em
22/09/2026 numa janela de 7 dias, ela errava 298 de 535 casos.

    python3 sync_interagiu.py                # dry-run dos últimos 14 dias
    python3 sync_interagiu.py --dias 30      # outra janela
    python3 sync_interagiu.py --apply        # aplica (só ADICIONA)
    python3 sync_interagiu.py --apply --remover   # também tira dos falsos positivos
    python3 sync_interagiu.py --revert <log.json>

ATENÇÃO: o PATCH do Kommo substitui a lista inteira de tags do lead. O script
sempre reenvia a lista completa, montada a partir dos nomes ORIGINAIS da API
(`Interagiu` tem I maiúsculo no Kommo), e só mexe nessa tag.
"""

import argparse, collections, csv, json, time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import fetch_kommo_imr as K   # .env, token, subdomínio e helpers

TAG = "Interagiu"
SAIDA = ("outgoing_chat_message", "entity_direct_message")
ENTRADA = ("incoming_chat_message",)
PIPELINES = (K.PIPELINE_SDR, K.PIPELINE_NUTRICAO)
BASE = f"https://{K.SUBDOMAIN}.kommo.com"


def _pagina(tipo, ts_de, ts_ate):
    """Um fatia da janela. Levanta se estourar o teto de páginas: truncar aqui
    faria lead com contato humano parecer 'sem resgate' e perder a tag."""
    out, page = [], 1
    while True:
        r = K.kommo_get("/api/v4/events", {
            "filter[type][]": tipo,
            "filter[created_at][from]": ts_de, "filter[created_at][to]": ts_ate,
            "limit": 250, "page": page})
        lote = (r.get("_embedded") or {}).get("events") or []
        if not lote:
            break
        out += lote
        if len(lote) < 250:
            break
        page += 1
        if page > 200:
            raise RuntimeError(
                f"{tipo}: fatia de {ts_de}..{ts_ate} passou de 50 mil eventos. "
                "Diminua FATIA_DIAS — truncar causaria remoção indevida de tag.")
        time.sleep(0.12)
    return out


FATIA_DIAS = 7   # janelas menores: cada fatia cabe folgada na paginação


def eventos(tipo, ts_de, ts_ate=None):
    """Varre a janela em fatias, pra nenhuma consulta chegar perto do teto."""
    ts_ate = ts_ate or int(datetime.now().timestamp())
    out, ini = [], ts_de
    passo = FATIA_DIAS * 86400
    while ini < ts_ate:
        fim = min(ini + passo, ts_ate)
        out += _pagina(tipo, ini, fim)
        ini = fim
    return out


def resgatados(ts_de):
    """{lead_id: (ts_1o_contato_humano, ts_1a_resposta_depois)}"""
    humano = {}
    for t in SAIDA:
        for e in eventos(t, ts_de):
            if e.get("entity_type") != "lead" or not e.get("created_by"):
                continue                      # created_by == 0 é bot/automação
            lid, ts = e["entity_id"], e["created_at"]
            if lid not in humano or ts < humano[lid]:
                humano[lid] = ts
    receb = collections.defaultdict(list)
    for t in ENTRADA:
        for e in eventos(t, ts_de):
            if e.get("entity_type") == "lead":
                receb[e["entity_id"]].append(e["created_at"])
    out = {}
    for lid, t0 in humano.items():
        depois = [ts for ts in receb.get(lid, []) if ts > t0]
        if depois:
            out[lid] = (t0, min(depois))
    return out, set(humano)


def carrega_leads(ids):
    """Tags atuais (nomes originais) e pipeline, em lotes."""
    info = {}
    ids = sorted(set(ids))
    for i in range(0, len(ids), 40):
        params = {"limit": 250}
        for j, lid in enumerate(ids[i:i + 40]):
            params[f"filter[id][{j}]"] = lid
        r = K.kommo_get("/api/v4/leads", params)
        for l in ((r.get("_embedded") or {}).get("leads") or []):
            info[l["id"]] = {
                "nome": l.get("name") or "",
                "pipeline": l.get("pipeline_id"),
                "tags": [(t.get("name") or "")
                         for t in ((l.get("_embedded") or {}).get("tags") or [])],
            }
        time.sleep(0.12)
    return info


def patch(lid, tags):
    r = requests.patch(f"{BASE}/api/v4/leads/{lid}",
                       headers={**K.hdrs(), "Content-Type": "application/json"},
                       json={"_embedded": {"tags": [{"name": t} for t in tags]}},
                       timeout=30)
    return r.ok, (r.status_code, r.text[:160])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=14, help="janela em dias (default 14)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--remover", action="store_true",
                    help="também retira a tag de quem não é resgate")
    ap.add_argument("--revert", metavar="LOG.json")
    a = ap.parse_args()

    if a.revert:
        log = json.loads(Path(a.revert).read_text(encoding="utf-8"))
        itens = log.get("aplicados") or []
        print(f"Revertendo {len(itens)} leads...")
        ok = sum(patch(p["id"], p["tags_antes"])[0] for p in itens)
        print(f"revertidos: {ok}/{len(itens)}")
        return

    ts_de = int((datetime.now() - timedelta(days=a.dias)).timestamp())
    print(f"Janela: últimos {a.dias} dias\nLendo eventos de mensagem...")
    resg, contatados = resgatados(ts_de)
    print(f"  {len(contatados)} leads receberam mensagem humana")
    print(f"  {len(resg)} responderam depois  → RESGATE\n")

    envolvidos = set(resg) | set(contatados)
    info = carrega_leads(envolvidos)
    info = {k: v for k, v in info.items() if v["pipeline"] in PIPELINES}

    plano = []
    for lid, d in info.items():
        tem = any(t.strip().lower() == TAG.lower() for t in d["tags"])
        deve = lid in resg
        if deve and not tem:
            plano.append({"id": lid, "acao": "adicionar", **d,
                          "tags_antes": d["tags"], "tags_depois": d["tags"] + [TAG]})
        elif tem and not deve and a.remover:
            novas = [t for t in d["tags"] if t.strip().lower() != TAG.lower()]
            plano.append({"id": lid, "acao": "remover", **d,
                          "tags_antes": d["tags"], "tags_depois": novas})

    c = collections.Counter(p["acao"] for p in plano)
    print(f"a adicionar: {c['adicionar']}")
    print(f"a remover  : {c['remover']}" + ("" if a.remover else "   (use --remover)"))

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    csv_path = f"sync_interagiu_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["lead_id", "nome", "acao", "tags_antes", "tags_depois"])
        for p in plano:
            w.writerow([p["id"], p["nome"], p["acao"],
                        " | ".join(p["tags_antes"]), " | ".join(p["tags_depois"])])
    print(f"\nCSV: {csv_path}")

    if not a.apply:
        print("\nDRY-RUN — nada foi escrito no Kommo.")
        return

    feitos, erros = [], []
    for i, p in enumerate(plano, 1):
        ok, det = patch(p["id"], p["tags_depois"])
        (feitos if ok else erros).append({**p, "erro": None if ok else det})
        if i % 25 == 0 or i == len(plano):
            print(f"  {i}/{len(plano)}...", flush=True)
        time.sleep(0.15)
    log_path = f"sync_interagiu_{stamp}.log.json"
    Path(log_path).write_text(json.dumps(
        {"quando": datetime.now().isoformat(), "aplicados": feitos, "erros": erros},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\naplicados: {len(feitos)} · erros: {len(erros)}\nlog: {log_path}")


if __name__ == "__main__":
    main()
