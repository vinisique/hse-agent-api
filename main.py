"""
main.py — Serviço FastAPI · Agente HSE-IT · Vivamente 360°
══════════════════════════════════════════════════════════════
Substitui o Streamlit como runtime do agente de IA.
Expõe endpoints HTTP que o Next.js chama internamente.

Variáveis de ambiente necessárias (.env):
    GROQ_API_KEY   = "gsk_..."
    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD  (pgvector RAG)
    API_SECRET_KEY = "chave-interna-entre-nextjs-e-python"

Instalar:
    pip install fastapi uvicorn groq python-dotenv \
                sentence-transformers psycopg2-binary pgvector

Rodar:
    uvicorn main:app --host 0.0.0.0 --port 8001 --workers 2
"""

from __future__ import annotations

import os
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from groq import Groq
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from rag import buscar_contexto_normativo
from prompts import SYSTEM_ANALYSIS, SYSTEM_PLAN

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Groq client (singleton) ──────────────────────────────────
_groq = Groq(api_key=os.environ["GROQ_API_KEY"])

# ── Segurança: chave compartilhada Next.js ↔ Python ─────────
_API_SECRET = os.environ.get("API_SECRET_KEY", "")
_bearer = HTTPBearer()

def verify_secret(creds: HTTPAuthorizationCredentials = Security(_bearer)):
    if not _API_SECRET or creds.credentials != _API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# ════════════════════════════════════════════════════════════
# MODELOS DE REQUEST / RESPONSE
# ════════════════════════════════════════════════════════════

class AnalysisRequest(BaseModel):
    chart_key:     str = Field(..., description="Identificador do gráfico, ex: 'igrp_bar'")
    chart_label:   str = Field(..., description="Nome legível do gráfico")
    chart_data:    Any = Field(..., description="Dados do gráfico (JSON livre)")
    campaign_name: str = Field(..., description="Nome da campanha")
    use_rag:      bool = Field(True, description="Se deve buscar contexto normativo via RAG")


class ActionPlanRequest(BaseModel):
    problem_title:   str        = Field(..., description="Título curto do problema")
    problem_desc:    str        = Field(..., description="Descrição completa do problema")
    problem_type:    str        = Field("", description="Tipo: Setor | Dimensão | Cargo | Geral")
    problem_group:   str        = Field("", description="Nome do grupo afetado")
    risk_class:      str        = Field("", description="Crítico | Importante | Moderado | Aceitável")
    nr_value:        float|None = Field(None, description="Valor NR do problema")
    pct_high_risk:   float|None = Field(None, description="% em risco alto (0–100)")
    worst_dimension: str        = Field("", description="Dimensão HSE mais crítica")
    use_rag:         bool       = Field(True)


class W5H2Action(BaseModel):
    id:       str
    what:     str        # O quê
    why:      str        # Por quê
    who:      str        # Quem
    where:    str        # Onde
    when:     str        # Quando
    how:      str        # Como
    how_much: str        # Quanto custa
    status:   str = "pending"


class PDCAStep(BaseModel):
    plan:  list[str]
    do:    list[str]
    check: list[str]
    act:   list[str]


class Problem(BaseModel):
    titulo:           str
    descricao:        str
    nivel_risco:      str
    dimensao_afetada: str = ""


class AnalysisResponse(BaseModel):
    analysis:    str
    problems:    list[Problem]
    action_plan: list[W5H2Action]
    pdca:        PDCAStep
    rag_used:    bool
    model:       str


class ActionPlanResponse(BaseModel):
    action_plan: list[W5H2Action]
    pdca:        PDCAStep
    rag_used:    bool
    model:       str


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

MODEL = "llama-3.3-70b-versatile"


def _call_groq(system: str, user_content: str, max_tokens: int = 4000) -> dict:
    """Chama o Groq e retorna o JSON parseado."""
    completion = _groq.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        temperature=0.3,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_content},
        ],
    )
    raw = completion.choices[0].message.content
    # Remove possível markdown fence residual
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
        clean = clean.rsplit("```", 1)[0]
    return json.loads(clean.strip())


def _safe_rag(query: str) -> str:
    """Busca RAG com fallback silencioso."""
    try:
        return buscar_contexto_normativo(query)
    except Exception as e:
        log.warning(f"RAG indisponível: {e}")
        return ""


def _build_analysis_prompt(req: AnalysisRequest, rag_ctx: str) -> str:
    data_str = json.dumps(req.chart_data, ensure_ascii=False, indent=2)
    prompt = (
        f'Campanha: "{req.campaign_name}"\n'
        f"Gráfico: {req.chart_label}\n\n"
        f"DADOS:\n```json\n{data_str}\n```\n"
    )
    if rag_ctx:
        prompt += f"\n\n{rag_ctx}\n"
    return prompt


def _build_plan_prompt(req: ActionPlanRequest, rag_ctx: str) -> str:
    prompt = (
        f"PROBLEMA HSE-IT:\n{req.problem_desc}\n\n"
        f"Tipo: {req.problem_type} | Grupo: {req.problem_group}\n"
        f"Classificação: {req.risk_class}"
    )
    if req.nr_value is not None:
        prompt += f" | NR: {req.nr_value:.1f}"
    if req.pct_high_risk is not None:
        prompt += f" | % risco alto: {req.pct_high_risk:.0f}%"
    if req.worst_dimension:
        prompt += f"\nDimensão crítica: {req.worst_dimension}"
    if rag_ctx:
        prompt += f"\n\n{rag_ctx}"
    prompt += "\n\nGere plano de ação 5W2H completo e específico."
    return prompt


def _parse_analysis(raw: dict) -> AnalysisResponse:
    """Normaliza a resposta do modelo para o schema de saída."""
    problems = [
        Problem(
            titulo=p.get("titulo", ""),
            descricao=p.get("descricao", ""),
            nivel_risco=p.get("nivel_risco", ""),
            dimensao_afetada=p.get("dimensao_afetada", ""),
        )
        for p in raw.get("problems", [])
    ]

    action_plan = [
        W5H2Action(
            id=a.get("id", f"acao_{i+1}"),
            what=a.get("what", ""),
            why=a.get("why", ""),
            who=a.get("who", ""),
            where=a.get("where", ""),
            when=a.get("when", ""),
            how=a.get("how", ""),
            how_much=a.get("how_much", ""),
            status=a.get("status", "pending"),
        )
        for i, a in enumerate(raw.get("action_plan", []))
    ]

    raw_pdca = raw.get("pdca", {})
    pdca = PDCAStep(
        plan=raw_pdca.get("plan", []),
        do=raw_pdca.get("do", []),
        check=raw_pdca.get("check", []),
        act=raw_pdca.get("act", []),
    )

    return AnalysisResponse(
        analysis=raw.get("analysis", ""),
        problems=problems,
        action_plan=action_plan,
        pdca=pdca,
        rag_used=False,  # preenchido no handler
        model=MODEL,
    )


def _parse_plan(raw: dict) -> tuple[list[W5H2Action], PDCAStep]:
    """Normaliza resposta de plano (suporta formato antigo do Streamlit e novo)."""
    if "action_plan" in raw:
        actions_raw = raw["action_plan"]
        pdca_raw    = raw.get("pdca", {})
    elif "acoes" in raw:
        # Compatibilidade com formato antigo (campos em português do Streamlit/Groq)
        actions_raw = [
            {
                "id":       f"acao_{i+1}",
                "what":     a.get("descricao", ""),
                "why":      a.get("porque", ""),
                "who":      a.get("responsavel", ""),
                "where":    a.get("onde", ""),
                "when":     a.get("prazo", ""),
                "how":      a.get("como", ""),
                "how_much": a.get("custo_investimento", ""),
                "status":   "pending",
            }
            for i, a in enumerate(raw["acoes"])
        ]
        pdca_raw = raw.get("pdca", {})
    else:
        actions_raw = []
        pdca_raw    = {}

    actions = [
        W5H2Action(
            id=a.get("id", f"acao_{i+1}"),
            what=a.get("what", ""),
            why=a.get("why", ""),
            who=a.get("who", ""),
            where=a.get("where", ""),
            when=a.get("when", ""),
            how=a.get("how", ""),
            how_much=a.get("how_much", ""),
            status=a.get("status", "pending"),
        )
        for i, a in enumerate(actions_raw)
    ]

    pdca = PDCAStep(
        plan=pdca_raw.get("plan", []),
        do=pdca_raw.get("do", []),
        check=pdca_raw.get("check", []),
        act=pdca_raw.get("act", []),
    )
    return actions, pdca


# ════════════════════════════════════════════════════════════
# APP
# ════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Agente HSE-IT iniciado — modelo: %s", MODEL)
    yield
    log.info("Agente HSE-IT encerrado")


app = FastAPI(
    title="Agente HSE-IT",
    description="API de análise psicossocial e geração de planos de ação 5W2H + PDCA",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # adicione o domínio de produção antes do deploy
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


# ── Endpoint 1: Análise completa (análise + problemas + 5W2H + PDCA) ──
@app.post("/insights/generate", response_model=AnalysisResponse)
def generate_insight(
    req: AnalysisRequest,
    _: bool = Depends(verify_secret),
):
    """
    Recebe dados de um gráfico e retorna análise textual,
    lista de problemas, plano 5W2H e PDCA.
    Chamado pelo Next.js quando o usuário clica em 'Gerar Análise'.
    """
    log.info("generate_insight: chart_key=%s campaign=%s", req.chart_key, req.campaign_name)

    # 1. RAG — busca contexto normativo relevante
    rag_ctx  = ""
    rag_used = False
    if req.use_rag:
        query    = f"{req.chart_label} riscos psicossociais {req.campaign_name}"
        rag_ctx  = _safe_rag(query)
        rag_used = bool(rag_ctx)

    # 2. Monta prompt e chama modelo
    user_prompt = _build_analysis_prompt(req, rag_ctx)
    try:
        raw = _call_groq(SYSTEM_ANALYSIS, user_prompt, max_tokens=4000)
    except json.JSONDecodeError as e:
        log.error("JSON parse error: %s", e)
        raise HTTPException(status_code=502, detail="Modelo retornou resposta inválida")
    except Exception as e:
        log.error("Groq error: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro no modelo: {e}")

    # 3. Normaliza e retorna
    result = _parse_analysis(raw)
    result.rag_used = rag_used
    return result


# ── Endpoint 2: Plano de ação para problema específico ──────
@app.post("/insights/action-plan", response_model=ActionPlanResponse)
def generate_action_plan(
    req: ActionPlanRequest,
    _: bool = Depends(verify_secret),
):
    """
    Recebe a descrição de um problema identificado e retorna
    um plano 5W2H + PDCA específico para aquele problema.
    Chamado quando o usuário clica em 'Gerar Plano' em um problema listado.
    """
    log.info("generate_action_plan: group=%s class=%s", req.problem_group, req.risk_class)

    # 1. RAG
    rag_ctx  = ""
    rag_used = False
    if req.use_rag:
        rag_ctx  = _safe_rag(req.problem_desc)
        rag_used = bool(rag_ctx)

    # 2. Modelo
    user_prompt = _build_plan_prompt(req, rag_ctx)
    try:
        raw = _call_groq(SYSTEM_PLAN, user_prompt, max_tokens=3000)
    except json.JSONDecodeError as e:
        log.error("JSON parse error: %s", e)
        raise HTTPException(status_code=502, detail="Modelo retornou resposta inválida")
    except Exception as e:
        log.error("Groq error: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro no modelo: {e}")

    # 3. Normaliza e retorna
    actions, pdca = _parse_plan(raw)
    return ActionPlanResponse(
        action_plan=actions,
        pdca=pdca,
        rag_used=rag_used,
        model=MODEL,
    )
