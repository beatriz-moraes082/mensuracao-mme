# Dashboard IMR — Ipioca Mar Resort

Dashboard dinâmico de performance de campanhas e funil comercial do Ipioca Mar Resort (IMR).

**Fontes:** Meta Ads · Kommo CRM · Google Ads *(em standby)*

---

## Estrutura

```
dashboard-imr/
├── index.html                          # Dashboard web (abre em qualquer navegador)
├── data/
│   ├── meta_spend.json                 # Gerado por fetch_meta_spend.py
│   ├── kommo_leads.json                # Gerado por fetch_kommo_imr.py
│   └── google_ads_spend.json           # Gerado por fetch_google_ads.py
├── fetch_meta_spend.py                 # Puxa investimento/leads Meta Ads
├── fetch_kommo_imr.py                  # Puxa funil Kommo (SDR/Closer/Duque)
├── fetch_google_ads.py                 # Puxa spend Google Ads (OAuth2)
├── relatorio_analise_leads_YYYY-MM-DD.md  # Relatórios de análise
├── .env                                # Tokens (NÃO VERSIONADO)
└── .env.example                        # Template de tokens
```

---

## Setup

### 1. Configurar tokens

```bash
cp .env.example .env
# Editar .env com os tokens reais
```

Tokens necessários:
- **KOMMO_TOKEN**: token long-lived da integração Kommo (`ipiocamarresort.kommo.com`)
- **META_TOKEN** + **META_ACCOUNT**: access token do Business Manager + `act_XXXXXXXXX`
- **GOOGLE_ADS_\***: developer token + OAuth client + customer_id (ver seção Google Ads abaixo)

### 2. Rodar os fetchers

```bash
python3 fetch_kommo_imr.py
python3 fetch_meta_spend.py
python3 fetch_google_ads.py   # opcional — requer OAuth browser na primeira execução
```

### 3. Visualizar dashboard

```bash
python3 -m http.server 3000
# Abrir http://localhost:3000
```

---

## Regras de cálculo (conforme cliente)

| Métrica | Regra |
|---------|-------|
| Leads | Funil SDR + Funil Nutrição (Duque), filtrados por data de criação |
| Leads Qualificados | SDR: `Lead Qualificado` + `Reunião Agendada` + `Reunião Realizada` |
| Reunião Agendada | SDR com tags `reunião-agendada`, `reunião-realizada`, `reagendar-reunião` |
| Reunião Realizada | SDR na etapa `Reunião Realizada` |
| Proposta | Closer: `Proposta Enviada` + `Follow-up` + `Sinal Verde` |
| Venda | Closer na etapa `Venda Ganha`, filtrado por **data de fechamento** |

Dedup automática: vendas do Closer com mesmo `contact_id` + mesma data de fechamento contam como 1.

---

## Google Ads OAuth (primeira execução)

1. O script abre o navegador em `accounts.google.com` pedindo autorização.
2. Faz login com conta que tem acesso à conta Google Ads do IMR.
3. Aceita o escopo `https://www.googleapis.com/auth/adwords`.
4. O script captura o `code`, troca por `refresh_token` e salva em `.google_ads_refresh_token` (gitignored).
5. Execuções seguintes usam o refresh_token automaticamente.

Se acessar via MCC, definir `GOOGLE_ADS_LOGIN_CUSTOMER_ID` no `.env`.

---

## Atualização dos relatórios

Os relatórios em markdown (`relatorio_analise_leads_*.md`) são gerados manualmente a partir dos dados dos fetchers. Para criar um novo:

1. Rodar `fetch_kommo_imr.py` e `fetch_meta_spend.py`
2. Copiar o relatório mais recente como base
3. Atualizar métricas a partir de `data/*.json`

---

*Trilha Performance Digital · MME Vacation · Ipioca Mar Resort*
