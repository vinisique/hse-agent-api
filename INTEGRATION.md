# Integração com o Serviço de IA — HSE-IT Agent

> **Para:** Time de Frontend / Backend (Next.js)  
> **De:** Engenharia de IA  
> **Serviço:** Python FastAPI · Agente HSE-IT · Vivamente 360°

---

## O que é este serviço

Um microserviço Python independente que recebe dados de gráficos/problemas HSE e retorna:
- Análise textual técnica
- Lista de problemas priorizados por risco
- Plano de ação 5W2H
- Ciclo PDCA

O Next.js **nunca** chama a Anthropic diretamente. Toda a inteligência passa por aqui.

---

## Variáveis de ambiente necessárias

### No `.env` do **Next.js** (adicionar)

```env
AI_SERVICE_URL=http://localhost:8001   # em produção: URL do servidor Python
AI_SECRET_KEY=sua-chave-interna-aqui   # mesma chave configurada no serviço Python
```

### No `.env` do **serviço Python** (arquivo separado)

```env
GROQ_API_KEY=gsk_...
API_SECRET_KEY=sua-chave-interna-aqui   # mesma do Next.js acima

# PostgreSQL com pgvector (para o módulo RAG)
PG_HOST=seu-host
PG_PORT=5432
PG_DB=hse_normas
PG_USER=seu-usuario
PG_PASSWORD=sua-senha
```

> ⚠️ O valor de `API_SECRET_KEY` precisa ser **idêntico** nos dois lados.  
> Se não tiver o PostgreSQL configurado, o RAG retorna vazio e o agente ainda funciona — só sem contexto normativo.

---

## Como subir o serviço Python localmente

```bash
# 1. Clonar o repo do agente (separado do Next.js)
git clone https://github.com/sua-org/vivamente-hse-agent
cd vivamente-hse-agent

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Criar o .env com as variáveis acima

# 4. Subir o servidor
uvicorn main:app --host 0.0.0.0 --port 8001 --workers 2
```

> ⚠️ **Atenção no primeiro start:** o serviço baixa ~560 MB do modelo de embeddings
> (`intfloat/multilingual-e5-large`). Isso ocorre apenas uma vez. Aguarde antes de testar.

### Verificar se está rodando

```bash
curl http://localhost:8001/health
# Esperado: {"status":"ok","model":"llama-3.3-70b-versatile"}
```

---

## Endpoints disponíveis

### `GET /health`
Verifica se o serviço está online.

---

### `POST /insights/generate`
**Quando usar:** usuário clica em "Gerar Análise" em qualquer gráfico do dashboard.

**Request:**
```typescript
const res = await fetch(`${process.env.AI_SERVICE_URL}/insights/generate`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${process.env.AI_SECRET_KEY}`,
  },
  body: JSON.stringify({
    chart_key:     'igrp_bar',              // identificador do gráfico (string livre)
    chart_label:   'IGRP por Dimensão',     // nome legível do gráfico
    chart_data:    { /* dados do gráfico */ }, // JSON livre com os dados
    campaign_name: 'Pesquisa Q1 2025 — SP', // nome da campanha
    use_rag:       true,                    // buscar contexto normativo (recomendado: true)
  }),
});
```

**Response 200:**
```typescript
{
  analysis: string;          // análise em 3–4 parágrafos
  problems: Array<{
    titulo: string;
    descricao: string;
    nivel_risco: 'crítico' | 'importante' | 'moderado' | 'aceitável';
    dimensao_afetada: string;
  }>;
  action_plan: Array<{
    id: string;
    what: string;   // O quê
    why: string;    // Por quê (inclui referência normativa)
    who: string;    // Quem (cargo/área)
    where: string;  // Onde
    when: string;   // Quando
    how: string;    // Como
    how_much: string; // Custo estimado
    status: 'pending';
  }>;
  pdca: {
    plan: string[];
    do: string[];
    check: string[];
    act: string[];
  };
  rag_used: boolean;
  model: string;      // "llama-3.3-70b-versatile"
}
```

---

### `POST /insights/action-plan`
**Quando usar:** usuário clica em "Gerar Plano" em um problema específico já listado.

**Request:**
```typescript
const res = await fetch(`${process.env.AI_SERVICE_URL}/insights/action-plan`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${process.env.AI_SECRET_KEY}`,
  },
  body: JSON.stringify({
    problem_title:   'Déficit de Controle no Financeiro',
    problem_desc:    'Score médio de 1.2/4 na dimensão Controle...',
    problem_type:    'Setor',         // 'Setor' | 'Dimensão' | 'Cargo' | 'Geral'
    problem_group:   'Financeiro',
    risk_class:      'Crítico',       // 'Crítico' | 'Importante' | 'Moderado' | 'Aceitável'
    nr_value:        16,              // NR calculado (número, opcional)
    pct_high_risk:   68,              // % em risco alto (0–100, opcional)
    worst_dimension: 'Controle',      // dimensão mais crítica (opcional)
    use_rag:         true,
  }),
});
```

**Response 200:** igual ao `action_plan` + `pdca` + `rag_used` + `model` do endpoint anterior.

---

## Tratamento de erros

| Status | Significado | O que fazer |
|--------|-------------|-------------|
| `401`  | `AI_SECRET_KEY` incorreta ou ausente | Verificar variáveis de ambiente nos dois lados |
| `422`  | Campos obrigatórios faltando no body | Verificar os campos `chart_key`, `chart_label`, `chart_data`, `campaign_name` |
| `502`  | Modelo retornou resposta inválida ou erro na Anthropic API | Logar e exibir mensagem genérica ao usuário |

```typescript
// Exemplo de tratamento no route.ts do Next.js
if (!res.ok) {
  if (res.status === 401) throw new Error('Configuração de chave inválida');
  if (res.status === 422) throw new Error('Dados do gráfico incompletos');
  throw new Error(`Serviço de IA indisponível (${res.status})`);
}
const insight = await res.json();
```

---

## Configuração de CORS em produção

O serviço Python está configurado para aceitar requests de `http://localhost:3000` por padrão.

Em produção, o time de IA precisa saber **qual é o domínio do Next.js** para liberar no CORS. Informe a URL antes do deploy.

---

## Dependências de infraestrutura (checklist pré-produção)

- [ ] Servidor Python acessível pelo Next.js (mesma rede ou URL pública)
- [ ] `AI_SERVICE_URL` configurada no ambiente de produção do Next.js
- [ ] `AI_SECRET_KEY` configurada nos dois serviços (igual)
- [ ] `GROQ_API_KEY` válida no servidor Python
- [ ] Primeira inicialização aguardada (download do modelo de embeddings ~560 MB)
- [ ] PostgreSQL com pgvector acessível (opcional — sem ele o RAG é desabilitado silenciosamente)
- [ ] CORS do serviço Python liberado para o domínio de produção do Next.js

---

## Exemplo completo — route.ts

```typescript
// src/app/api/campaigns/[id]/insights/route.ts

import { NextRequest, NextResponse } from 'next/server';

const AI_URL    = process.env.AI_SERVICE_URL ?? 'http://localhost:8001';
const AI_SECRET = process.env.AI_SECRET_KEY  ?? '';

export async function POST(req: NextRequest) {
  const body = await req.json();

  const res = await fetch(`${AI_URL}/insights/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${AI_SECRET}`,
    },
    body: JSON.stringify({
      chart_key:     body.chartKey,
      chart_label:   body.chartLabel,
      chart_data:    body.chartData,
      campaign_name: body.campaignName,
      use_rag:       true,
    }),
  });

  if (!res.ok) {
    const status = res.status === 401 ? 401 : 502;
    return NextResponse.json({ error: 'AI service error' }, { status });
  }

  const insight = await res.json();
  return NextResponse.json(insight);
}
```

---

## Dúvidas

Qualquer dúvida sobre o contrato de dados, entrar em contato com a Engenharia de IA antes de implementar o consumo no frontend.
