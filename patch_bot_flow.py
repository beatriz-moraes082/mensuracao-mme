#!/usr/bin/env python3
"""
Aplica as alterações restantes de tags no fluxo de pré-atendimento do IMR.

Entrada : export do Kommo já com o bloco 358 (Excluir) feito na interface.
Saída   : export novo, pronto pra importar como outra cópia de teste.

Alterações:
  1. Restaura o bloco "Definir campo → Pré-atendimento: Versão 1" (id 284 /
     step 74), que foi apagado sem querer ao criar o 358. Volta pra cadeia
     79 → 284 → 94.
  2. Novo bloco ANTES DA 2ª PERGUNTA (id 18), recebendo as duas ligações que
     hoje vão direto pra lá (id 174 e o ramo "else" do id 172):
     unset [bot-nao-iniciado, bot-concluído] + set [bot-incompleto]
  4. Corrige o bloco 346 (step 87), que hoje só ADICIONA bot-nao-iniciado:
     passa a remover as outras duas antes. Esse bloco NÃO é órfão — o step 46
     ("no_answer") aponta pra ele via o Pausar 326. Era o que faltava enxergar.
  5. Troca o Pausar 326 de 299s para 600s (a janela de 10 min combinada).

Codificação confirmada no export da Bia: adicionar = set_tag, remover =
unset_tag, ambos com {"type": 2, "value": [...]}.  unset_tag remove só as
tags listadas — não mexe em interagiu, reunião-realizada etc.
"""

import json, sys, uuid
from pathlib import Path

ORIGEM = "/Users/anabeatrizmoraes/mensuracao-mme/bot-flows/[Teste_tags]_ Pré-atendimento.json"
DESTINO = "bot-flows/bot-CORRIGIDO-pre-atendimento-tags.json"

# --- blocos de referência -------------------------------------------------
P2 = 18                                  # id 18 = 2ª pergunta ("Já se hospedaram…")
ANTES_P2 = [174, 172]                    # quem aponta pro 18 hoje
MSG_TRANSF, TAGS_FIM = 79, 94            # id 79 -> id 94  (vira 79 -> 284 -> 94)
PAUSAR_NAOINIC, TAGS_NAOINIC = 326, 346   # vivos via no_answer do step 46

VERSAO_CF = {                            # bloco 284, recuperado do export anterior
    "name": "set_custom_fields",
    "params": {
        "type": "lead",
        "value": "{{lead.cf.4329027.7957673}}",
        "value_type": "value",
        "custom_field": "{{lead.cf.4329027}}",
    },
}


def acoes_tag(remover, adicionar):
    return [
        {"handler": "action", "params": {"name": "unset_tag",
                                         "params": {"type": 2, "value": remover}}},
        {"handler": "action", "params": {"name": "set_tag",
                                         "params": {"type": 2, "value": [adicionar]}}},
    ]


def main():
    o = json.loads(Path(ORIGEM).read_text(encoding="utf-8"))
    inner = json.loads(o["model"]["text"])
    pos = json.loads(o["model"]["positions"])
    byid = {b["id"]: b for b in pos}

    prox_step = max(int(k) for k in inner if k.isdigit()) + 1
    prox_id = max(b["id"] for b in pos) + 1
    step_de_id = {b["id"]: b.get("step") for b in pos}

    def novo_bloco(nome, acoes, destino_id, x, y, z):
        """Cria o bloco no modelo e no canvas, já apontando pro destino."""
        nonlocal prox_step, prox_id
        st, bid = prox_step, prox_id
        prox_step += 1
        prox_id += 1
        uid = str(uuid.uuid4())
        inner[str(st)] = {
            "question": acoes + [{"handler": "goto",
                                  "params": {"type": "question",
                                             "step": step_de_id[destino_id]}}],
            "block_uuid": uid,
        }
        pos.append({
            "x": x, "y": y, "z": z, "id": bid, "goto": {"block": destino_id},
            "name": nome, "step": st, "type": "question",
            "width": 400, "height": 109, "deletable": True, "block_uuid": uid,
            "actions": [{"id": 900 + i, "sort": i, "links": [], "params": a}
                        for i, a in enumerate(acoes)],
        })
        step_de_id[bid] = st
        return bid, st

    def religa(origem_id, de_id, para_id, para_step):
        """Troca o destino de origem_id: de_id -> para_id, no canvas e no modelo."""
        b = byid[origem_id]
        if (b.get("goto") or {}).get("block") == de_id:
            b["goto"]["block"] = para_id
        for a in (b.get("actions") or []):
            for l in (a.get("links") or []):
                if l.get("block") == de_id:
                    l["block"] = para_id
        st = str(b.get("step"))
        de_step = step_de_id[de_id]
        def anda(no):
            if isinstance(no, dict):
                if no.get("handler") == "goto" and (no.get("params") or {}).get("step") == de_step:
                    no["params"]["step"] = para_step
                for v in no.values():
                    anda(v)
            elif isinstance(no, list):
                for v in no:
                    anda(v)
        anda(inner[st])

    # ── 1. restaura o bloco da versão do pré-atendimento ──────────────────
    uid284 = str(uuid.uuid4())
    st284 = prox_step; prox_step += 1
    inner[str(st284)] = {
        "question": [{"handler": "action", "params": VERSAO_CF},
                     {"handler": "goto",
                      "params": {"type": "question", "step": step_de_id[TAGS_FIM]}}],
        "block_uuid": uid284,
    }
    id284 = prox_id; prox_id += 1
    ref = byid[TAGS_FIM]
    pos.append({
        "x": ref["x"], "y": ref["y"] - 160, "z": 22, "id": id284,
        "goto": {"block": TAGS_FIM}, "name": "Definir campo", "step": st284,
        "type": "question", "width": 400, "height": 0, "deletable": True,
        "block_uuid": uid284,
        "actions": [{"id": 895, "sort": 0, "links": [], "params":
                     {"handler": "action", "params": VERSAO_CF}}],
    })
    step_de_id[id284] = st284
    religa(MSG_TRANSF, TAGS_FIM, id284, st284)
    print(f"1. bloco da versão restaurado  → id {id284} (step {st284}); {MSG_TRANSF} → {id284} → {TAGS_FIM}")

    # ── 2. bloco antes da 2ª pergunta: bot-incompleto ─────────────────────
    r = byid[P2]
    id_inc, st_inc = novo_bloco(
        "Gerenciar tags",
        acoes_tag(["bot-nao-iniciado", "bot-concluído"], "bot-incompleto"),
        P2, r["x"] - 420, r["y"] + 180, r.get("z", 10),
    )
    for orig in ANTES_P2:
        religa(orig, P2, id_inc, st_inc)
    print(f"2. antes da 2ª pergunta → id {id_inc} (step {st_inc}); {ANTES_P2} → {id_inc} → {P2}")

    # ── 4. bloco 346 (step 87) passa a remover as outras tags ────────────
    st87 = str(step_de_id[TAGS_NAOINIC])
    inner[st87]["question"] = [
        {"handler": "action", "params": {"name": "unset_tag", "params": {
            "type": 2, "value": ["bot-incompleto", "bot-concluído"]}}}
    ] + inner[st87]["question"]
    b346 = byid[TAGS_NAOINIC]
    b346["actions"] = [{"id": 950, "sort": 0, "links": [], "params":
        {"handler": "action", "params": {"name": "unset_tag", "params": {
            "type": 2, "value": ["bot-incompleto", "bot-concluído"]}}}}] + [
        {**a, "sort": a["sort"] + 1} for a in b346["actions"]]
    print(f"4. bloco {TAGS_NAOINIC} (step {st87}) agora remove incompleto+concluído antes de marcar nao-iniciado")

    # ── 5. Pausar 299s → 600s ─────────────────────────────────────────────
    st86 = str(step_de_id[PAUSAR_NAOINIC])
    for h in inner[st86]["question"]:
        for c in (h.get("params") or {}).get("conditions", []):
            if (c.get("event") or {}).get("source") == "timer":
                antes = c["event"]["delay"]; c["event"]["delay"] = 600
                print(f"5. Pausar {PAUSAR_NAOINIC} (step {st86}): delay {antes}s → 600s")
    for a in (byid[PAUSAR_NAOINIC].get("actions") or []):
        ev = ((a.get("params") or {}).get("params") or {}).get("event") or {}
        if ev.get("source") == "timer":
            ev["delay"] = 600

    o["model"]["text"] = json.dumps(inner, ensure_ascii=False)
    o["model"]["positions"] = json.dumps(pos, ensure_ascii=False)
    Path(DESTINO).write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    print(f"\ngravado: {DESTINO}")


if __name__ == "__main__":
    main()
