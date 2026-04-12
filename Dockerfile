FROM python:3.11-slim

WORKDIR /app

# Instala dependências do sistema para psycopg2
RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pré-baixa o modelo de embeddings (multilingual-e5-large ~560 MB)
# Evita timeout no primeiro request em produção
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"

# Copia o código
COPY main.py prompts.py rag.py ./

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
