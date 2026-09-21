#!/usr/bin/env python3
"""
Corrige as tags de estado do bot no Kommo (IMR).

Regra de resolução (fechada com a Bia em 21/09/2026):
  · tem 'bot-concluído'            -> bot-concluído
  · senão, 1+ campos respondidos   -> bot-incompleto
  · senão (zero respostas)         -> bot-nao-iniciado

As três tags são mutuamente exclusivas: a que sobra remove as outras duas.
A tag 'interagiu' (e qualquer outra) NUNCA é tocada.

Escopo: pipelines SDR + Nutrição, leads por DATA DE CRIAÇÃO no mês alvo.

    python3 fix_bot_tags.py                      # dry-run (não escreve nada)
    python3 fix_bot_tags.py --apply              # aplica
    python3 fix_bot_tags.py --revert <log.json>  # desfaz uma aplicação

ATENÇÃO: o PATCH do Kommo SUBSTITUI a lista inteira de tags do lead — não
existe "remover uma tag". Por isso o script sempre reenvia a lista completa,
montada a partir dos nomes ORIGINAIS vindos da API (sem lowercase), e só
troca a tag de estado do bot.
"""

import argparse, csv, json, sys, time
from datetime import datetime
from pathlib import Path

import requests

import fetch_kommo_imr as K   # reaproveita .env, token, constantes e helpers

BOT_TAGS = {"bot-concluído", "bot-incompleto", "bot-nao-iniciado"}

# Campos coletados pelo fluxo ativo "Pré-atendimento IMR [13/04/26]".
# Qualquer um preenchido = o lead respondeu ao menos uma pergunta do bot.
#
# ATENÇÃO: no Kommo do IMR essas respostas ficam no CONTATO, não no lead
# (ver process_lead() do fetch_kommo_imr.py, que lê tudo de contact.get(...)).
# Ler do lead devolve sempre vazio e classificaria todo mundo como
# 'bot-nao-iniciado'.
CAMPOS_BOT = [
    ("idade",        K.CF_IDADE),
    ("hosp_allinc",  K.CF_HOSP_ALLINC),
    ("prox_ferias",  K.CF_PROX_FERIAS),
    ("investimento", K.CF_INVESTIMENTO),
    ("freq_viagem",  K.CF_FREQ_VIAGEM),
    ("cep",          K.CF_CEP),
    ("profissao",    K.CF_PROFISSAO),
]

PIPELINES = [K.PIPELINE_SDR, K.PIPELINE_NUTRICAO]
BASE = f"https://{K.SUBDOMAIN}.kommo.com"


# ─────────────────────────────────────────────────────────── leitura

def mes_range(ym):
    ini = datetime(int(ym[:4]), int(ym[5:7]), 1)
    fim = datetime(ini.year + (ini.month == 12), (ini.month % 12) + 1, 1)
    return int(ini.timestamp()), int(fim.timestamp()) - 1


def busca_leads(ts_de, ts_ate):
    """Puxa leads FRESCOS da API — as tags podem ter mudado desde o snapshot."""
    out = []
    for pid in PIPELINES:
        page = 1
        while True:
            r = K.kommo_get("/api/v4/leads", {
                "filter[pipeline_id]": pid,
                "filter[created_at][from]": ts_de,
                "filter[created_at][to]": ts_ate,
                "with": "contacts",   # precisa do contato: é nele que ficam as respostas
                "limit": 250,
                "page": page,
            })
            lote = (r.get("_embedded") or {}).get("leads") or []
            if not lote:
                break
            out.extend(lote)
            page += 1
            time.sleep(0.15)
    return out


def tags_raw(lead):
    """Nomes ORIGINAIS das tags (sem lowercase) — é o que volta no PATCH."""
    return [(t.get("name") or "") for t in ((lead.get("_embedded") or {}).get("tags") or [])]


def n_respostas(lead, contatos):
    """Quantas perguntas do bot o lead respondeu — lido do CONTATO."""
    c = contatos.get(K.lead_contact_id(lead)) or {}
    return sum(1 for _, fid in CAMPOS_BOT if (c.get(fid) or "").strip())


def alvo(lead, contatos):
    atuais = {t.strip().lower() for t in tags_raw(lead)}
    if "bot-concluído" in atuais:
        return "bot-concluído"
    return "bot-incompleto" if n_respostas(lead, contatos) > 0 else "bot-nao-iniciado"


# ─────────────────────────────────────────────────────────── plano

def monta_plano(leads, contatos):
    plano = []
    for l in leads:
        orig = tags_raw(l)
        atuais_bot = {t.strip().lower() for t in orig} & BOT_TAGS
        destino = alvo(l, contatos)
        if atuais_bot == {destino}:
            continue                      # já está certo, não toca
        # preserva tudo que não é tag de estado do bot, na ordem original
        novas = [t for t in orig if t.strip().lower() not in BOT_TAGS] + [destino]
        plano.append({
            "id": l["id"],
            "nome": l.get("name") or "",
            "criado_em": datetime.fromtimestamp(l.get("created_at") or 0).strftime("%d/%m/%Y %H:%M"),
            "respostas": n_respostas(l, contatos),
            "de": sorted(atuais_bot) or ["SEM TAG"],
            "para": destino,
            "tags_antes": orig,
            "tags_depois": novas,
        })
    return plano


def escreve_csv(plano, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["lead_id", "nome", "criado_em", "respostas_do_bot",
                    "tag_bot_antes", "tag_bot_depois", "todas_tags_antes", "todas_tags_depois"])
        for p in plano:
            w.writerow([p["id"], p["nome"], p["criado_em"], p["respostas"],
                        " + ".join(p["de"]), p["para"],
                        " | ".join(p["tags_antes"]), " | ".join(p["tags_depois"])])


# ─────────────────────────────────────────────────────────── escrita

def aplica(plano, log_path):
    feitos, erros = [], []
    for i, p in enumerate(plano, 1):
        body = {"_embedded": {"tags": [{"name": t} for t in p["tags_depois"]]}}
        try:
            r = requests.patch(f"{BASE}/api/v4/leads/{p['id']}", headers={
                **K.hdrs(), "Content-Type": "application/json"
            }, json=body, timeout=30)
            if r.ok:
                feitos.append(p)
            else:
                erros.append({**p, "http": r.status_code, "resp": r.text[:200]})
        except Exception as e:
            erros.append({**p, "http": "EXC", "resp": str(e)[:200]})
        if i % 25 == 0 or i == len(plano):
            print(f"  {i}/{len(plano)}...", flush=True)
        time.sleep(0.15)                  # respeita o rate limit do Kommo

    Path(log_path).write_text(json.dumps({
        "quando": datetime.now().isoformat(),
        "aplicados": feitos, "erros": erros,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return feitos, erros


def reverte(log_path):
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    itens = log.get("aplicados") or []
    print(f"Revertendo {len(itens)} leads para as tags originais...")
    ok = 0
    for i, p in enumerate(itens, 1):
        body = {"_embedded": {"tags": [{"name": t} for t in p["tags_antes"]]}}
        r = requests.patch(f"{BASE}/api/v4/leads/{p['id']}", headers={
            **K.hdrs(), "Content-Type": "application/json"
        }, json=body, timeout=30)
        ok += bool(r.ok)
        if i % 25 == 0 or i == len(itens):
            print(f"  {i}/{len(itens)}...", flush=True)
        time.sleep(0.15)
    print(f"revertidos: {ok}/{len(itens)}")


# ─────────────────────────────────────────────────────────── main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", default="2026-09", help="mês alvo (YYYY-MM), por data de criação")
    ap.add_argument("--apply", action="store_true", help="aplica de verdade (default é dry-run)")
    ap.add_argument("--revert", metavar="LOG.json", help="desfaz uma aplicação anterior")
    a = ap.parse_args()

    if a.revert:
        return reverte(a.revert)

    ts_de, ts_ate = mes_range(a.mes)
    print(f"Buscando leads de {a.mes} (SDR + Nutrição, por data de criação)...")
    leads = busca_leads(ts_de, ts_ate)
    print(f"  {len(leads)} leads no período")

    print("Buscando contatos (é neles que ficam as respostas do bot)...")
    contatos = K.get_contacts_map([K.lead_contact_id(l) for l in leads if K.lead_contact_id(l)])
    print(f"  {len(contatos)} contatos")

    com_resp = sum(1 for l in leads if n_respostas(l, contatos) > 0)
    print(f"  {com_resp} leads com ao menos 1 resposta do bot "
          f"({com_resp/max(len(leads),1)*100:.1f}%)\n")
    if com_resp == 0:
        sys.exit("ABORTADO: nenhum lead com resposta — sinal de erro na leitura "
                 "dos campos. Não faz sentido marcar todo mundo como não-iniciado.")

    plano = monta_plano(leads, contatos)
    print(f"já corretos : {len(leads) - len(plano)}")
    print(f"a corrigir  : {len(plano)}\n")

    # Distribuição final (como o mês fica DEPOIS de aplicar o plano)
    dist = {}
    for l in leads:
        d = alvo(l, contatos)
        dist[d] = dist.get(d, 0) + 1
    print(f"distribuição de {a.mes} (após correção):")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {v:5d}  {k:<18} {v/max(len(leads),1)*100:5.1f}%")
    print()

    resumo = {}
    for p in plano:
        resumo[(" + ".join(p["de"]), p["para"])] = resumo.get((" + ".join(p["de"]), p["para"]), 0) + 1
    print(f"{'de':<42}{'para':<20}{'n':>6}")
    for (de, para), n in sorted(resumo.items(), key=lambda x: -x[1]):
        print(f"{de:<42}{para:<20}{n:>6}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    csv_path = f"fix_bot_tags_{a.mes}_{stamp}.csv"
    escreve_csv(plano, csv_path)
    print(f"\nCSV com antes/depois: {csv_path}")

    if not a.apply:
        print("\nDRY-RUN — nada foi escrito no Kommo.")
        print("Revise o CSV e rode de novo com --apply para aplicar.")
        return

    print(f"\nAplicando {len(plano)} alterações no Kommo...")
    log_path = f"fix_bot_tags_{a.mes}_{stamp}.log.json"
    feitos, erros = aplica(plano, log_path)
    print(f"\naplicados: {len(feitos)} · erros: {len(erros)}")
    print(f"log de reversão: {log_path}")
    if erros:
        print("  (rode com --revert nesse log para desfazer)")


if __name__ == "__main__":
    main()
