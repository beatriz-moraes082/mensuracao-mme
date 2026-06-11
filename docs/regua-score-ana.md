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

> ⚠️ **IMPORTANTE — Este critério vem do bot ANTIGO (intermediário de
> maio/26 · `bot-v2-inicial-2026-05-05.json`), que tinha a pergunta**
> *"Como sua família normalmente se hospeda quando viaja?"* com a opção
> "Resorts All Inclusive". Esse bot foi **descontinuado** quando os
> testes A/B (v1 LONGO + v2 CURTO) entraram em produção.
>
> **Leads NOVOS** (que passam pelos bots atuais) **não conseguem ser
> classificados como A automaticamente**, porque nenhum dos 2 bots em
> produção tem essa pergunta. Só leads **históricos do bot mai/26**
> entram em A pela régua.

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

## 📌 Mapeamento bot → régua

A régua usa abstrações ("pergunta 1", "pergunta 5", "Sim, tenho vontade")
que vinham do bot intermediário de mai/26. A função `calcLeadScore()`
no `index.html` precisa reconhecer as variações dos bots atuais
pra continuar funcionando.

### Mapeamento de "pergunta 5" (Interesse em Resort All-Inclusive)

| Régua (abstração) | Bot v1/v2 atual P22 | Bot v1/v2 atual P235 | Bot mai/26 inicial | Bot v1 antigo |
|---|---|---|---|---|
| **"Sim, tenho vontade"** | `Sim, tenho interesse` | `Sim, quero conhecer` | `Sim, tenho vontade` | `Quero continuar viajando` · `Gostaria de ter primeira experiência` |
| **"Talvez"** | — | `Depende da oferta` | `Talvez` · `Depende do destino` | `Talvez, se houver uma boa oportunidade` |
| **"Não procuro esse tipo de hospedagem"** | `Não tenho interesse` | `Não tenho interesse` | `Não é o que procuro` | `Não tenho interesse em resort all inclusive` |

### Mapeamento de "pergunta 1" (define Lead A) — **só existe no bot antigo**

| Bot | Pergunta 1 do bot | Opção que define A |
|---|---|---|
| Bot mai/26 (descontinuado) | "Como sua família normalmente se hospeda quando viaja?" | **Resorts All Inclusive** ✅ |
| Bot v1 atual (LONGO) | "Qual sua idade?" | ❌ não aplicável |
| Bot v2 atual (CURTO) | "Me diz uma coisa, o que você estava buscando?" | ❌ não aplicável |

---

## Ordem de avaliação implementada

```
1. hospedagem == "Resorts All Inclusive"  → A  (só leads do bot mai/26)
2. Investimento até R$ 5.000               → D
3. "Talvez" / "Não procuro"                → D
4. "Sim, tenho vontade" + gasto > R$ 10.001 → B
5. "Sim, tenho vontade" + gasto R$ 5.001-10.000 → C
6. Caso contrário                          → Incompleto
```

A primeira que casar define o perfil. **Leads dos bots atuais (v1/v2)
nunca casam com a regra 1**, então sempre caem em B, C, D ou Incompleto.
