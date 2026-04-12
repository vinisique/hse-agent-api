"""
rag.py — Módulo RAG · Agente HSE-IT · Vivamente 360°
──────────────────────────────────────────────────────
Versão FastAPI: remove dependência do Streamlit.
O modelo de embedding é cacheado como singleton de módulo
(carregado uma vez quando o worker inicia).

Variáveis de ambiente necessárias:
    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD
"""

from __future__ import annotations

import logging
import os

import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────
EMBEDDING_MODEL     = "intfloat/multilingual-e5-large"
RELEVANCE_THRESHOLD = 0.50
DEFAULT_TOP_K       = 5

DOC_LABELS = {
    "ISO_45003_Preview"      : "ISO 45003:2021 (Preview WMS)",
    "WHO_ILO_2022"           : "WHO/ILO — Mental Health at Work (2022)",
    "Guia_MTE_Psicossocial"  : "Guia MTE — Riscos Psicossociais",
    "ISO_45003_2021"         : "ISO 45003:2021",
    "Guia_ASSP_ISO45003"     : "Guia ASSP / ISO 45003",
    "NR-1_2025"              : "NR-1 (2025)",
    "NR-7_PCMSO"             : "NR-7 (PCMSO)",
    "NR-17_Ergonomia"        : "NR-17 (Ergonomia)",
    "Portaria_MTE_1419_2024" : "Portaria MTE nº 1.419/2024",
    "Manual_GRO_PGR_NR1"     : "Manual GRO/PGR da NR-1",
}

# ─────────────────────────────────────────────
# SINGLETON DO MODELO — carregado uma vez
# ─────────────────────────────────────────────
_model: SentenceTransformer | None = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        log.info("Carregando modelo de embeddings: %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        log.info("Modelo carregado.")
    return _model


# ─────────────────────────────────────────────
# CONEXÃO — nova a cada chamada (sem idle leak)
# ─────────────────────────────────────────────
def _get_conn() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ["PG_DB"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        options="-c statement_timeout=30000",
        connect_timeout=10,
    )
    register_vector(conn)
    return conn


# ─────────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ─────────────────────────────────────────────
def buscar_contexto_normativo(
    pergunta: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = RELEVANCE_THRESHOLD,
) -> str:
    """
    Recebe a pergunta/contexto e retorna string formatada
    com os trechos normativos mais relevantes para injetar no prompt.
    Retorna string vazia se nenhum trecho atingir o threshold.
    """
    if not pergunta or not pergunta.strip():
        return ""

    # Embedding
    try:
        model = _get_model()
        query_vector = model.encode(
            f"query: {pergunta}",
            normalize_embeddings=True,
        ).tolist()
    except Exception as e:
        log.warning("Erro ao gerar embedding: %s", e)
        return ""

    # Busca pgvector
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                documento,
                texto,
                1 - (embedding <=> %s::vector) AS score
            FROM documentos_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """, (query_vector, query_vector, top_k))
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        log.warning("Erro na busca normativa: %s", e)
        return ""
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if not rows:
        return ""

    trechos = []
    docs_usados: set[str] = set()

    for doc_id, texto, score in rows:
        if score < threshold:
            continue
        texto = texto.strip()
        if not texto:
            continue
        label = DOC_LABELS.get(doc_id, doc_id)
        docs_usados.add(label)
        trechos.append(f"[Fonte: {label} | Relevância: {score:.0%}]\n{texto}")

    if not trechos:
        return ""

    fontes_str = " · ".join(sorted(docs_usados))
    return (
        "════════════════════════════════════════════\n"
        "BASE NORMATIVA RELEVANTE PARA ESTA RESPOSTA\n"
        f"Fontes: {fontes_str}\n"
        "════════════════════════════════════════════\n\n"
        + "\n\n---\n\n".join(trechos)
        + "\n\n════════════════════════════════════════════"
    )


# ─────────────────────────────────────────────
# UTILITÁRIO — lista documentos indexados
# ─────────────────────────────────────────────
def listar_documentos_indexados() -> dict:
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM documentos_chunks;")
        total = cur.fetchone()[0]
        cur.execute("""
            SELECT documento, COUNT(*) AS chunks
            FROM documentos_chunks
            GROUP BY documento
            ORDER BY documento;
        """)
        por_documento = {row[0]: row[1] for row in cur.fetchall()}
        cur.close()
        return {"total_vetores": total, "por_documento": por_documento, "status": "online"}
    except Exception as e:
        return {"status": "offline", "erro": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
