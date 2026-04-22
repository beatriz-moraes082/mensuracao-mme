# Relatório de Análise: Leads × Público × Criativo
**Cliente:** Ipioca Mar Resort (IMR) | **Agência:** Trilha Performance Digital / MME Vacation  
**Período:** 17/03/2026 – 15/04/2026 (últimos 30 dias)  
**Gerado em:** 16/04/2026  
**Fontes:** Meta Ads API v21.0 | Kommo CRM *(aguardando reconexão)*

---

## ⚠️ Status das Fontes de Dados

| Fonte | Status | Impacto |
|-------|--------|---------|
| Meta Ads API | ✅ Conectado | Dados completos de spend, leads, CPL por adset e criativo |
| Kommo CRM | ❌ Desconectado | Análises de Lead Score, funil, ROAS e CAC indisponíveis |

**Análises disponíveis neste relatório:** 3 (parcial), 14 (parcial), 15 (parcial)  
**Análises bloqueadas:** 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 (requerem Kommo)

---

## 1. Pré-Verificação de Qualidade dos Dados

> ⚠️ **Verificação de campos Kommo (Campanha, Criativo, Lead Score, Valor) não pôde ser executada** — Kommo desconectado.

### Meta Ads — Verificação de Gaps de Investimento

```
Adsets com gasto > R$50 e 0 leads (possível desperdício):
  LokaLike 2% Compradores | IG       → R$ 280,49 → 1 lead (CPL R$ 280,49) ⚠️ CRÍTICO
  Interesses Geolocalizados [RESORTS] → R$ 113,82 → 0 leads               ⚠️ CRÍTICO
  BR | IG | [+] Férias                → R$  63,12 → 0 leads               ⚠️
  LokaLike 2% Lista de Clientes       → R$  61,00 → 0 leads               ⚠️

Criativos com gasto > R$50 e 0 leads:
  VD03               → R$ 113,20 → 0 leads  ⚠️ CRÍTICO
  24/12 - Confiança  → R$  69,47 → 0 leads  ⚠️

Total estimado de investimento sem retorno em leads: ~R$ 575 (15,3% do orçamento)
```

---

## 2. Resumo Executivo

1. **298 leads** gerados em 30 dias com investimento de **R$ 3.744,11** → CPL médio de **R$ 12,56**
2. **2 públicos concentram 95% dos leads**: RJ/DF/MT/MS/GO (136 leads) e Engajamento 365D (113 leads)
3. **Melhor CPL por público**: Engajamento 365D a **R$ 8,71** — 31% mais barato que a média
4. **2 criativos concentram 89% dos leads**: VD02 (151 leads, R$11,02 CPL) e BN02 (115 leads, R$10,83 CPL)
5. **Melhor combinação geral**: Engajamento 365D × BN02 com **CPL R$ 8,48** — mais barato e eficiente
6. **~R$ 575 em orçamento desperdiçado** em adsets/criativos sem nenhum lead gerado
7. **VD03 e 24/12 - Confiança** gastaram R$ 183 sem gerar nenhum lead → considerar pausar
8. Criativos VD01|Ana e 16/02-Depoimento têm CPL elevado (R$37 e sem leads) → ineficientes
9. Análises de qualidade (Score A/B, funil, ROAS, CAC) pendentes até reconexão do Kommo
10. Prioridade imediata: escalar Engajamento 365D × VD02 e Engajamento 365D × BN02

---

## 3. Análise por Público (Adset) — Meta CPL

| Público | Investimento | Leads | CPL | % do Total | Recomendação |
|---------|-------------|-------|-----|-----------|--------------|
| 30-55 \| RJ/DF/MT/MS/GO \| Resort All-inc. | R$ 1.442,04 | 136 | R$ 10,60 | 45,6% | 🟢 MANTER |
| 27-55 \| *Engajamento 365D | R$ 983,97 | 113 | **R$ 8,71** | 37,9% | 🟢 **ESCALAR** |
| 30-55 \| SP/MG \| Resort All-inclusive | R$ 738,79 | 46 | R$ 16,06 | 15,4% | 🟡 AVALIAR |
| 30-55 \| LokaLike 2% Compradores \| IG | R$ 280,49 | 1 | R$ 280,49 | 0,3% | 🔴 **PAUSAR** |
| 26-50 \| RO/AM/MS/MT/AP/TO/RR \| Viajantes | R$ 14,25 | 1 | R$ 14,25 | 0,3% | ⚪ Teste |
| 26-50 \| LokaLike 2% Clientes IMR | R$ 8,60 | 1 | R$ 8,60 | 0,3% | ⚪ Teste |
| 30-55 \| Interesses Geolocalizados | R$ 113,82 | 0 | — | 0% | 🔴 **PAUSAR** |
| 27-55 \| BR \| IG \| [+] Férias | R$ 63,12 | 0 | — | 0% | 🔴 **PAUSAR** |
| 30-55 \| LokaLike 2% Lista Clientes | R$ 61,00 | 0 | — | 0% | 🔴 **PAUSAR** |
| 30-55 \| LokaLike % Site Lead 180D | R$ 18,39 | 0 | — | 0% | 🔴 Pausar |
| 27-55 \| Engajamento MME (365D) \| IG | R$ 13,74 | 0 | — | 0% | 🔴 Pausar |
| 27-55 \| LokaLike 2% Comp. \| [+]Família | R$ 5,90 | 0 | — | 0% | 🔴 Pausar |

> ⚠️ **Nota:** Este é CPL bruto (Meta). CPL de lead qualificado requer dados do Kommo.

---

## 14. Análise por Criativo (Ad) — Meta CPL

| Criativo | Investimento | Leads | CPL | % do Total | Recomendação |
|---------|-------------|-------|-----|-----------|--------------|
| VD02 | R$ 1.663,54 | 151 | **R$ 11,02** | 50,7% | 🟢 **ESCALAR** |
| BN02 | R$ 1.245,15 | 115 | R$ 10,83 | 38,6% | 🟢 **ESCALAR** |
| BN01 | R$ 453,43 | 27 | R$ 16,79 | 9,1% | 🟡 AVALIAR |
| VD01 \| Ana | R$ 186,03 | 5 | R$ 37,21 | 1,7% | 🔴 Pausar |
| VD03 | R$ 113,20 | 0 | — | 0% | 🔴 **PAUSAR** |
| 24/12 - Confiança | R$ 69,47 | 0 | — | 0% | 🔴 **PAUSAR** |
| 16/02 - Depoimento | R$ 13,29 | 0 | — | 0% | 🔴 Pausar |

> **Criativos VD03, 24/12-Confiança e 16/02-Depoimento gastaram R$ 196,00 sem gerar nenhum lead.**

---

## 15. Combinação Público × Criativo — Ranking de Performance

| Público | Criativo | Leads | CPL | Ranking | Ação |
|---------|---------|-------|-----|---------|------|
| *Engajamento 365D | BN02 | 38 | **R$ 8,48** | 🥇 | **ESCALAR** |
| *Engajamento 365D | VD02 | 74 | R$ 8,68 | 🥈 | **ESCALAR** |
| RJ/DF/MT/MS/GO | VD02 | 74 | R$ 9,98 | 🥉 | MANTER/ESCALAR |
| RJ/DF/MT/MS/GO | BN02 | 44 | R$ 10,05 | 4° | MANTER |
| SP/MG | BN02 | 32 | R$ 14,02 | 5° | Avaliar |
| RJ/DF/MT/MS/GO | BN01 | 17 | R$ 15,24 | 6° | Avaliar |
| SP/MG | BN01 | 9 | R$ 18,89 | 7° | Avaliar |
| SP/MG | VD01 \| Ana | 4 | R$ 19,29 | 8° | Pausar |
| Demais combinações | — | ≤1 | >R$ 14 | — | Pausar |

---

## Análises Pendentes (requerem Kommo CRM)

| # | Análise | O que precisa |
|---|---------|---------------|
| 1 | Qual público traz mais Score A? | Campo Lead Score + Campanha no Kommo |
| 2 | Qual público traz mais Score B? | Campo Lead Score + Campanha no Kommo |
| 3* | CPL qualificado por público | Leads que atingiram etapa qualificada |
| 4 | Avanço no funil por público | Histórico de etapas |
| 5 | O que leads qualificados têm em comum? | Campos do card de contato |
| 6 | % de avanço entre etapas | Funil completo |
| 7 | Gargalo do funil | Análise 6 |
| 8 | Respostas em comum dos leads que avançam | Campos de formulário |
| 9 | % de ganho e receita | Negócios ganhos + valor |
| 10 | ROAS geral e por público | Receita dos negócios ganhos |
| 11 | CAC geral e por público | Negócios ganhos |
| 12 | Qual criativo traz mais Score A? | Campo Lead Score + Criativo no Kommo |
| 13 | Qual criativo traz mais Score B? | Idem |
| 14* | CPL qualificado por criativo | Leads qualificados por criativo |

*Disponível parcialmente (CPL bruto do Meta)

---

## Recomendações Finais

### 🟢 Escalar imediatamente
- **Público:** `27-55 | *Engajamento 365D` — melhor CPL (R$8,71), 37,9% dos leads
- **Criativo:** `VD02` e `BN02` — únicos com volume e CPL competitivo
- **Combinação top:** `Engajamento 365D × BN02` (CPL R$8,48) e `Engajamento 365D × VD02` (CPL R$8,68)

### 🔴 Pausar imediatamente
- **Adsets:** LokaLike 2% Compradores (CPL R$280), Interesses Geolocalizados, BR|Férias, LokaLike Lista, Site Lead 180D, Engajamento MME, LokaLike Família
- **Criativos:** VD03, 24/12-Confiança, 16/02-Depoimento — R$196 gastos, 0 leads

### ⚡ Ação prioritária: reconectar Kommo
Sem os dados de Lead Score e funil, não é possível saber se os leads baratos são também os mais qualificados. O CPL barato no Meta não garante qualidade — é essencial cruzar com o Score do Kommo.

**Para reconectar o Kommo:**
1. Acesse `somostrilha.kommo.com` → Configurações → Integrações
2. Localize a integração com Client ID `a2880bc3-9be4-4dad-8378-dac0bb94381f`
3. Copie o **Redirect URI** configurado na integração
4. Gere um novo access token ou compartilhe o Redirect URI correto

---

*Relatório gerado automaticamente | Trilha Performance Digital · MME Vacation · Ipioca Mar Resort*
