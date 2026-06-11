# 🤖 Fluxos de Pré-atendimento · Bot do IMR

Pasta com **histórico dos bots de pré-atendimento** que rodam no Kommo CRM
do Ipioca Mar Resort. Cada arquivo `.json` é uma exportação do Salesbot do
Kommo (formato proprietário) numa versão específica.

Importante pra evitar erros de mapeamento na régua de score: **as labels
das respostas mudam entre versões**. A função `calcLeadScore()` no
`index.html` precisa cobrir todas as versões pra histórico continuar
classificado corretamente.

---

## 📚 Versões catalogadas

### 1. `bot-v2-inicial-2026-05-05.json` (05/05/2026)

Versão intermediária do bot v2, ativa em maio/26. **Esse é o bot que a
Ana usou de referência quando escreveu a régua de score**.

**Perguntas e respostas:**

```
Bloco 5 · "Como sua família normalmente se hospeda quando viaja?"
   ▸ Resort All Inclusive
   ▸ Resorts
   ▸ Hotéis
   ▸ Casa ou apartamento
   ▸ Pousadas
   ▸ Nenhuma dessas acima

Bloco 8 · "Você costuma viajar mais:"
   ▸ Em casal · Com filhos · Com família · Com amigos · Sozinhos

Bloco 15 · "Hoje, quanto vocês costumam investir por ano em viagens?"
   ▸ Até R$ 5.000
   ▸ R$ 5.001 - R$ 10.000
   ▸ Acima de R$ 10.001

Bloco 30 · CEP

Bloco 49 · "Você teria interesse em se hospedar em Resorts All Inclusive?"
   ▸ Sim, tenho vontade        ← termo usado na régua da Ana
   ▸ Talvez
   ▸ Depende do destino
   ▸ Não é o que procuro       ← termo usado na régua da Ana

Bloco 56 · Idade
```

**Resumo extraído em `_extracted_questions_v2_inicial.txt`.**

---

### 2. `bot-v2-atual-pre22-p235.json` ⚠️ **PENDENTE**

Versão atual do bot v2 (≈jun/26+). Tem **ramificação P22/P235**
dependendo da resposta em "Já se hospedou em All-Inclusive?":

```
Bloco 22 · (mostrado SE 'Já hospedou = Sim')
   "Você tem interesse em continuar viajando para Resort All-inclusive?"
   ▸ Sim, tenho interesse
   ▸ Não tenho interesse

Bloco 235 · (mostrado SE 'Já hospedou = Não')
   "Você gostaria de ter sua primeira experiência em um Resort All-inclusive?"
   ▸ Sim, quero conhecer
   ▸ Depende da oferta
   ▸ Não tenho interesse

Investimento (mantém a granularidade do v2 inicial mas com 5 faixas):
   ▸ Até R$ 5.000
   ▸ Entre R$ 5.001 e R$ 7.000
   ▸ Entre R$ 7.001 e R$ 10.000
   ▸ Acima de R$ 10.001
   ▸ Não invisto em férias
```

📥 **TODO:** exportar este arquivo do Kommo (Configurações → Salesbots →
'Pré-atendimento' → ⋯ → Exportar JSON) e salvar aqui como
`bot-v2-atual-pre22-p235.json`.

---

## 🔄 Mapping de respostas entre versões

A função `calcLeadScore()` no `index.html` precisa reconhecer todas estas
strings ao avaliar `prox_ferias`:

| Régua Ana (abstração) | Bot v2 inicial (mai/26) | Bot v2 atual P22 (já hospedou) | Bot v2 atual P235 (não hospedou) |
|---|---|---|---|
| **"Sim, tenho vontade"** | `Sim, tenho vontade` | `Sim, tenho interesse` | `Sim, quero conhecer` |
| **"Talvez"** | `Talvez` · `Depende do destino` | — | `Depende da oferta` |
| **"Não procuro"** | `Não é o que procuro` | `Não tenho interesse` | `Não tenho interesse` |

E também labels antigos do bot v1 (até abril/26):
- `Quero continuar viajando para resorts all inclusive`
- `Gostaria de ter minha primeira experiência em resort all inclusive`
- `Talvez, se houver uma boa oportunidade`
- `Não tenho interesse em resort all inclusive`

---

## 🧩 Custom fields do Kommo mapeados

Pra cada pergunta do bot existe um custom field correspondente no
contato/lead. Conferir no `fetch_kommo_imr.py` as constantes `CF_*`:

| Campo | ID Kommo | Versão |
|---|---|---|
| `CF_HOSPEDAGEM` | 4226162 | v2 (Como se hospeda) |
| `CF_VIAJA_MAIS` | 4226170 | v2 (Com quem viaja) |
| `CF_INVESTIMENTO` | 4226176 | v2 (Quanto investe/ano) |
| `CF_INTERESSE_AI` | 4226180 | v2 inicial (Interesse em Resort All-Inc) |
| `CF_HOSP_ALLINC` | 4324059 | v2 atual (Hospedou All-Inc Sim/Não) |
| `CF_PROX_FERIAS` | 4324061 | v2 atual (P22/P235) |
| `CF_FREQ_VIAGEM` | 4324063 | v2 atual (Frequência) |
| `CF_IDADE` | 2824620 | v1+v2 |
| `CF_CEP` | 2824624 | v1+v2 |
| `CF_PROFISSAO` | 2824622 | v1+v2 |
| `CF_CUSTO_ANO` | 2824632 | **v1 só** (legado) |
| `CF_DESAFIO` | 2824630 | **v1 só** (legado) |
| `CF_VIAGEM_PROG` | 2824628 | **v1 só** (legado) |
| `CF_TIMESHARE` | 2824626 | **v1 só** (legado) |

---

## 📝 Como atualizar este diretório quando o bot mudar

1. No Kommo: **Configurações → Salesbots → [bot] → ⋯ → Exportar JSON**
2. Salva aqui com nome `bot-v{X}-{descrição}-{YYYY-MM-DD}.json`
3. Roda o script abaixo pra extrair perguntas legíveis:
   ```bash
   python3 -c "
   import json
   d = json.load(open('bot-flows/SEU_ARQUIVO.json'))
   text = json.loads(d['model']['text']) if isinstance(d['model']['text'], str) else d['model']['text']
   for bid in sorted(text.keys(), key=lambda x: int(x) if x.isdigit() else 999):
       block = text[bid]
       q = block.get('question') if isinstance(block, dict) else None
       if not isinstance(q, list): continue
       for item in q:
           if item.get('handler') == 'send_message':
               p = item.get('params', {})
               t = p.get('text','').strip()
               btns = [b.get('text','') for b in (p.get('buttons') or [])]
               if t:
                   print(f'\\nBloco {bid}: {t}')
                   for b in btns: print(f'   ▸ {b}')
   "
   ```
4. Atualiza o README aqui com a nova versão + mapping
5. Se respostas mudaram, ajusta `calcLeadScore()` em `index.html` pra
   reconhecer as novas labels
