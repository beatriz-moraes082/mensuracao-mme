# 🎯 Régua de Score · Classificação Automática do Lead

> **Autora:** Ana (gestora do CRM)
> **Cliente:** Ipioca Mar Resort / MME Vacation
> **Última confirmação pela Bia:** 11/06/2026
>
> ⚠️ **Esta é a régua OFICIAL.** Não alterar sem confirmação da Bia/Ana.
> Qualquer mudança no `calcLeadScore()` em `index.html` deve respeitar
> estes critérios exatos.

---

## Critérios

### 🟢 Lead A — Perfil Ideal

**Critério:**
- Marcou **Resorts All Inclusive** na **pergunta 1**

> Esse é o perfil que **já está acostumado com o modelo**.

---

### 🟡 Lead B — Perfil Aspiracional Premium

**Critérios (TODOS):**
- Não usa all inclusive atualmente
- Respondeu **"Sim, tenho vontade"** na **pergunta 5**
- Gasta **acima de R$ 10.001** por ano em viagens

---

### 🟠 Lead C — Perfil Aspiracional Médio

**Critérios (TODOS):**
- Não usa all inclusive atualmente
- Respondeu **"Sim, tenho vontade"** na **pergunta 5**
- Gasta **entre R$ 5.001 e R$ 10.000**

---

### 🔴 Lead D — Baixa aderência

**Critérios (qualquer um):**
- Gasta **até R$ 5.000**, ou
- Respondeu **"Talvez"** ou **"Não procuro esse tipo de hospedagem"**

---

## 📌 Notas de implementação · mapeamento bot

A régua usa abstrações ("pergunta 1", "pergunta 5", "Sim, tenho vontade")
que mapeiam pra perguntas reais dos bots em produção. A função
`calcLeadScore()` no `index.html` precisa reconhecer todas as variações.

### Mapeamento de "pergunta 5" (Interesse em Resort All-Inclusive)

| Régua (abstração) | Bot v1/v2 atual P22 | Bot v1/v2 atual P235 | Bot mai/26 inicial | Bot v1 antigo |
|---|---|---|---|---|
| **"Sim, tenho vontade"** | `Sim, tenho interesse` | `Sim, quero conhecer` | `Sim, tenho vontade` | `Quero continuar viajando` · `Gostaria de ter primeira experiência` |
| **"Talvez"** | — | `Depende da oferta` | `Talvez` · `Depende do destino` | `Talvez, se houver uma boa oportunidade` |
| **"Não procuro esse tipo de hospedagem"** | `Não tenho interesse` | `Não tenho interesse` | `Não é o que procuro` | `Não tenho interesse em resort all inclusive` |

### ⚠️ Pendência · "pergunta 1" da régua A

Os bots v1 e v2 atuais (`bot-flows/bot-pre-atendimento-v{1,2}.json`)
**NÃO têm uma pergunta sobre "Como se hospeda nas viagens"** com opção
"Resorts All Inclusive" (essa pergunta existia no bot intermediário de
mai/26, `bot-v2-inicial-2026-05-05.json`).

**Confirmar com a Bia/Ana qual é a "pergunta 1" da régua A no fluxo
atual.** Hipóteses:
1. A régua se refere ao bot v2 inicial e não foi atualizada
2. "Marcou Resorts All Inclusive" pode equivaler a:
   - `hosp_allinc = Sim` (já se hospedou) → pessoa tem familiaridade
   - `o_que_buscava = "Hospedagem"` (pergunta 1 do v2 atual)
3. Outro critério

**Até confirmação, a implementação atual usa o campo `hospedagem` (legado)
quando ele está presente.**

---

## Ordem de avaliação implementada

```
1. Resorts All Inclusive na "pergunta 1" → A
2. Gasta até R$ 5.000  → D
3. "Talvez" / "Não procuro" → D
4. "Sim, tenho vontade" + gasto > R$ 10.001 → B
5. "Sim, tenho vontade" + gasto R$ 5.001-10.000 → C
6. Caso contrário → Incompleto
```

A primeira que casar define o perfil.
