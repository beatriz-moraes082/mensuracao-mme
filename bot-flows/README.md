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

### 1. `bot-pre-atendimento-v1.json` 🟦 (versão LONGA · em teste A/B)

**8 perguntas** — mais completa, captura mais dados pra qualificação.

| # | Bloco | Pergunta | Campo Kommo |
|---|---|---|---|
| 1 | 0 | Qual sua idade? | `idade` |
| 2 | 5 | Nos últimos dez anos, você ou sua família já se hospedaram em Resorts All Inclusive? (Sim/Não) | `hosp_allinc` |
| 3 | 8 | **(se Sim na 2)** Você tem interesse em continuar viajando para Resort All-inclusive? | `prox_ferias` (P22) |
| 4 | 15 | Hoje, quanto vocês costumam investir por ano em viagens? | `investimento` |
| 5 | 30 | CEP | `cep` |
| 6 | 60 | Pra finalizar, qual a sua profissão? | `profissao` |
| 7 | 63 | Com que frequência você costuma viajar de férias? | `freq_viagem` |
| 8 | 70 | **(se Não na 2)** Você gostaria de ter sua primeira experiência em um Resort All-inclusive? | `prox_ferias` (P235) |

### 2. `bot-pre-atendimento-v2.json` 🟪 (versão CURTA · em teste A/B)

**5 perguntas** — mais rápida, foca no essencial pra qualificação.

| # | Bloco | Pergunta | Campo Kommo |
|---|---|---|---|
| 1 | 0 | Me diz uma coisa, o que você estava buscando quando enviou seu cadastro? | `o_que_buscava` |
| 2 | 5 | Nos últimos dez anos, você ou sua família já se hospedaram em Resorts All Inclusive? (Sim/Não) | `hosp_allinc` |
| 3 | 8 | **(se Sim na 2)** Você tem interesse em continuar viajando para Resort All-inclusive? | `prox_ferias` (P22) |
| 4 | 15 | Hoje, quanto vocês costumam investir por ano em viagens? | `investimento` |
| 5 | 70 | **(se Não na 2)** Você gostaria de ter sua primeira experiência em um Resort All-inclusive? | `prox_ferias` (P235) |

### 3. `bot-v2-inicial-2026-05-05.json` (versão INTERMEDIÁRIA · maio/26)

Versão usada como base inicial pra régua da Ana. Tem 'Sim, tenho vontade',
'Talvez', 'Depende do destino', 'Não é o que procuro'. Mantido pra
compatibilidade — leads classificados com essa versão usam essas labels.

---

## 🔄 Comparativo v1 vs v2 (testes A/B)

| Campo | v1 (longo) | v2 (curto) | Em ambos |
|---|---|---|---|
| `hosp_allinc` | ✅ | ✅ | ✅ |
| `prox_ferias` (P22/P235) | ✅ | ✅ | ✅ |
| `investimento` | ✅ | ✅ | ✅ |
| `idade` | ✅ | ❌ | só v1 |
| `freq_viagem` | ✅ | ❌ | só v1 |
| `profissao` | ✅ | ❌ | só v1 |
| `cep` | ✅ | ❌ | só v1 |
| `o_que_buscava` | ❌ | ✅ | só v2 |

**Por isso a aba "Respostas do Pré-atendimento" agora tem 4 seções:**
- 🟢 **Em ambos os fluxos** (3 campos sempre coletados)
- 🟦 **Exclusivo v1 LONGO** (4 campos só pros leads que fizeram v1)
- 🟪 **Exclusivo v2 CURTO** (1 campo só pros leads que fizeram v2)
- 🟠 **Legado** (campos de bots antigos descontinuados)

---

## 🔄 Mapping de respostas entre versões (régua da Ana)

A função `calcLeadScore()` no `index.html` precisa reconhecer todas estas
strings ao avaliar `prox_ferias`:

| Régua Ana (abstração) | v1+v2 P22 (já hospedou) | v1+v2 P235 (não hospedou) | Bot mai/26 inicial | Bot v1 antigo |
|---|---|---|---|---|
| **"Sim, tenho vontade"** | `Sim, tenho interesse` | `Sim, quero conhecer` | `Sim, tenho vontade` | `Quero continuar viajando` · `Gostaria de ter primeira experiência` |
| **"Talvez"** | — | `Depende da oferta` | `Talvez` · `Depende do destino` | `Talvez, se houver uma boa oportunidade` |
| **"Não procuro"** | `Não tenho interesse` | `Não tenho interesse` | `Não é o que procuro` | `Não tenho interesse em resort all inclusive` |

---

## 🧩 Custom fields do Kommo mapeados

Pra cada pergunta do bot existe um custom field correspondente. Conferir
no `fetch_kommo_imr.py` as constantes `CF_*`:

| Campo | ID Kommo | Versões que coletam |
|---|---|---|
| `CF_HOSPEDAGEM` | 4226162 | legado (não está em v1/v2 atuais) |
| `CF_VIAJA_MAIS` | 4226170 | legado |
| `CF_INVESTIMENTO` | 4226176 | **v1 + v2 (atual)** |
| `CF_INTERESSE_AI` | 4226180 | legado |
| `CF_HOSP_ALLINC` | 4324059 | **v1 + v2 (atual)** |
| `CF_PROX_FERIAS` | 4324061 | **v1 + v2 (atual)** — P22/P235 |
| `CF_FREQ_VIAGEM` | 4324063 | **v1 (só)** |
| `CF_IDADE` | 2824620 | **v1 (só)** |
| `CF_CEP` | 2824624 | **v1 (só)** |
| `CF_PROFISSAO` | 2824622 | **v1 (só)** |
| `CF_CUSTO_ANO` | 2824632 | legado |
| `CF_DESAFIO` | 2824630 | legado |
| `CF_VIAGEM_PROG` | 2824628 | legado |
| `CF_TIMESHARE` | 2824626 | legado |
| `CF_O_QUE_BUSCAVA` | (busca por nome) | **v2 (só)** |

---

## 📝 Como atualizar este diretório quando o bot mudar

1. No Kommo: **Configurações → Salesbots → [bot] → ⋯ → Exportar JSON**
2. Salva aqui com nome `bot-{descrição}.json`
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
4. Atualiza este README + mapping
5. Se respostas mudaram, ajusta `calcLeadScore()` em `index.html` pra
   reconhecer as novas labels + classifica corretamente no histórico
