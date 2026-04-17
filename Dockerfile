FROM python:3.11-slim

WORKDIR /app

# Dependências de sistema para psycopg2
RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements de produção (sem CUDA)
COPY requirements.prod.txt .

# Instala torch CPU-only primeiro (índice específico evita baixar versão CUDA)
RUN pip install --no-cache-dir \
    torch==2.11.0 \
    --index-url https://download.pytorch.org/whl/cpu

# Instala restante das dependências
RUN pip install --no-cache-dir -r requirements.prod.txt

# Pré-baixa o modelo de embeddings (~560 MB) — evita timeout no primeiro request
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"

# Copia o código
COPY main.py prompts.py rag.py llm_provider.py ./

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
