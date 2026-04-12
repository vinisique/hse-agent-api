# vivamente-hse-agent

Microserviço Python de IA — Agente HSE-IT · Vivamente 360°

Expõe endpoints HTTP consumidos pelo Next.js para análise de riscos psicossociais, geração de planos de ação 5W2H e PDCA, com suporte a RAG normativo (NR-1, ISO 45003, NR-17, etc.).

---

## Estrutura do repositório

```
vivamente-hse-agent/
├── main.py          # FastAPI app — endpoints /insights/generate e /insights/action-plan
├── prompts.py       # System prompts do agente (SYSTEM_ANALYSIS, SYSTEM_PLAN, SYSTEM_ADJUST)
├── rag.py           # Módulo RAG — busca semântica no PostgreSQL + pgvector
├── requirements.txt # Dependências Python
├── Dockerfile       # Container para produção
├── .env.example     # Variáveis de ambiente necessárias (nunca commitar o .env real)
├── .gitignore
└── README.md
```

---

## Setup local

### 1. Clonar e entrar no projeto

```bash
git clone https://github.com/sua-org/vivamente-hse-agent
cd vivamente-hse-agent
```

### 2. Criar ambiente virtual (recomendado)

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
.venv\Scripts\activate          # Windows
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Editar .env com suas chaves reais
```

### 5. Subir o servidor

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

> ⚠️ **Primeiro start:** o modelo de embeddings (`intfloat/multilingual-e5-large`, ~560 MB)
> é baixado automaticamente. Aguarde antes de fazer requests.

### 6. Verificar

```bash
curl http://localhost:8001/health
# {"status":"ok","model":"claude-sonnet-4-20250514"}
```

---

## Variáveis de ambiente

Criar um arquivo `.env` na raiz (nunca commitar):

```env
# Groq
GROQ_API_KEY=gsk_...

# Chave compartilhada com o Next.js (Bearer token)
API_SECRET_KEY=gere-uma-string-aleatoria-longa

# PostgreSQL + pgvector (módulo RAG — opcional)
PG_HOST=localhost
PG_PORT=5432
PG_DB=hse_normas
PG_USER=postgres
PG_PASSWORD=sua-senha
```

Se o PostgreSQL não estiver configurado, o RAG desabilita silenciosamente e o agente funciona sem contexto normativo.

---

## API

Ver `INTEGRATION.md` para documentação completa dos endpoints.

Resumo:

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET`  | `/health` | Health check |
| `POST` | `/insights/generate` | Análise completa de gráfico |
| `POST` | `/insights/action-plan` | Plano 5W2H para problema específico |

---

## Deploy com Docker

```bash
docker build -t hse-agent .
docker run -p 8001:8001 --env-file .env hse-agent
```

---

## Dependências principais

| Biblioteca | Função |
|------------|--------|
| `fastapi` | Framework HTTP |
| `groq` | SDK Groq (llama-3.3-70b-versatile) |
| `sentence-transformers` | Embeddings para RAG |
| `psycopg2-binary` + `pgvector` | Busca semântica no PostgreSQL |
| `python-dotenv` | Leitura do `.env` |
