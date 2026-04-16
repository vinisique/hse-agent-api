"""
main.py — Serviço FastAPI · Agente HSE-IT · Vivamente 360°
══════════════════════════════════════════════════════════════
Expõe endpoints HTTP que o Next.js chama internamente.

Variáveis de ambiente necessárias (.env):
    LLM_PROVIDER   = openrouter | openai | anthropic   (padrão: openrouter)

    # OpenRouter (padrão)
    OPENROUTER_API_KEY = "sk-or-..."
    OPENROUTER_MODEL   = "meta-llama/llama-3.3-70b-instruct"  (opcional)

    # OpenAI
    OPENAI_API_KEY = "sk-..."
    OPENAI_MODEL   = "gpt-4o"  (opcional)

    # Anthropic
    ANTHROPIC_API_KEY = "sk-ant-..."
    ANTHROPIC_MODEL   = "claude-sonnet-4-5"  (opcional)

    PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD  (pgvector RAG — opcional)
    API_SECRET_KEY = "chave-interna-entre-nextjs-e-python"

Instalar:
    pip install fastapi uvicorn openai anthropic python-dotenv \
                sentence-transformers psycopg2-binary pgvector

Rodar:
    uvicorn main:app --host 0.0.0.0 --port 8001 --workers 2
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from llm_provider import get_llm_provider
from rag import buscar_contexto_normativo
from prompts import (
    SYSTEM_ANALYSIS,
    SYSTEM_PLAN,
    SYSTEM_FINDINGS,
    SYSTEM_PLAN_CORRECTIVE,
    SYSTEM_PLAN_PREVENTIVE,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

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


class FindingsRequest(BaseModel):
    campaign_name: str = Field(..., description="Nome da campanha")
    campaign_data: Any = Field(
        ...,
        description=(
            "Dados da campanha estruturados: scores por dimensão, "
            "breakdowns por setor/cargo/unidade, histórico de campanhas anteriores (opcional)"
        ),
    )
    use_rag: bool = Field(True, description="Se deve buscar contexto normativo via RAG")


class ActionPlanRequest(BaseModel):
    problem_title:          str        = Field(..., description="Título curto do problema / finding")
    problem_desc:           str        = Field(..., description="Descrição completa do problema / finding")
    problem_type:           str        = Field("", description="Tipo: Setor | Dimensão | Cargo | Unidade | Geral")
    problem_group:          str        = Field("", description="Nome do grupo afetado")
    risk_class:             str        = Field("", description="Crítico | Importante | Moderado | Aceitável")
    nr_value:               float|None = Field(None, description="Valor NR do problema")
    pct_high_risk:          float|None = Field(None, description="% em risco alto (0–100)")
    worst_dimension:        str        = Field("", description="Dimensão HSE mais crítica")
    recommended_action_type: str       = Field(
        "corrective",
        description="Tipo de plano: 'corrective' (NC) | 'preventive' (FRE) | 'generic' (legado)",
    )
    regulatory_basis:       list[str]  = Field(default_factory=list, description="Normas aplicáveis ao finding")
    risk_factors:           list[str]  = Field(default_factory=list, description="Fatores de risco (apenas FRE)")
    plan_hint:              str        = Field("", description="Direção de plano sugerida pela API de findings")
    use_rag:                bool       = Field(True)


class W5H2Action(BaseModel):
    id:       str
    what:     str
    why:      str
    who:      str
    where:    str
    when:     str
    how:      str
    how_much: str
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


# ── Finding models ───────────────────────────────────────────

class NonConformity(BaseModel):
    """NC — Não Conformidade: situação que já viola limiar e exige plano corretivo imediato."""
    id:                      str
    type:                    Literal["NC"]
    category:                str
    group:                   str
    severity:                Literal["critical", "significant"]
    nr_value:                float
    pct_high_risk:           float
    worst_dimension:         str
    title:                   str
    description:             str
    regulatory_basis:        list[str]
    recommended_action_type: Literal["corrective"]
    urgency:                 Literal["immediate", "short_term"]
    plan_hint:               str


class EmergingRiskFactor(BaseModel):
    """FRE — Fator de Risco Emergente: padrão preocupante que justifica plano preventivo."""
    id:                      str
    type:                    Literal["FRE"]
    category:                str
    group:                   str
    severity:                Literal["moderate", "low"]
    nr_value:                float
    pct_high_risk:           float
    worst_dimension:         str
    title:                   str
    description:             str
    regulatory_basis:        list[str]
    risk_factors:            list[str]
    recommended_action_type: Literal["preventive"]
    urgency:                 Literal["planned", "monitoring"]
    plan_hint:               str


class FindingsSummary(BaseModel):
    total_findings: int
    nc_count:       int
    fre_count:      int
    critical_nc:    int
    model:          str


class FindingsResponse(BaseModel):
    findings: list[NonConformity | EmergingRiskFactor]
    summary:  FindingsSummary
    rag_used: bool


class AnalysisResponse(BaseModel):
    analysis:    str
    problems:    list[Problem]
    action_plan: list[W5H2Action]
    pdca:        PDCAStep
    rag_used:    bool
    model:       str


class ActionPlanResponse(BaseModel):
    action_plan:             list[W5H2Action]
    pdca:                    PDCAStep
    recommended_action_type: str
    rag_used:                bool
    model:                   str


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

def _safe_rag(query: str) -> str:
    try:
        return buscar_contexto_normativo(query)
    except Exception as e:
        log.warning("RAG indisponível: %s", e)
        return ""


def _build_analysis_prompt(req: AnalysisRequest, rag_ctx: str) -> str:
    data_str = json.dumps(req.chart_data, ensure_ascii=False, indent=2)
    prompt = (
        f'Campanha: "{req.campaign_name}"\n'
        f"Gráfico: {req.chart_label}\n\n"
        f"<chart_data>\n{data_str}\n</chart_data>\n"
    )
    if rag_ctx:
        prompt += f"\n<normative_context>\n{rag_ctx}\n</normative_context>\n"
    return prompt


def _build_findings_prompt(req: FindingsRequest, rag_ctx: str) -> str:
    data_str = json.dumps(req.campaign_data, ensure_ascii=False, indent=2)
    prompt = (
        f'Campanha: "{req.campaign_name}"\n\n'
        f"<campaign_data>\n{data_str}\n</campaign_data>\n"
    )
    if rag_ctx:
        prompt += f"\n<normative_context>\n{rag_ctx}\n</normative_context>\n"
    return prompt


def _build_plan_prompt(req: ActionPlanRequest, rag_ctx: str) -> str:
    """
    Constrói o prompt do usuário para /insights/action-plan.
    Usa a tag <finding> para NC/FRE e <problem> para o fluxo legado genérico.
    """
    if req.recommended_action_type in ("corrective", "preventive"):
        tag = "finding"
        content = (
            f"Título: {req.problem_title}\n"
            f"Tipo: NC\n" if req.recommended_action_type == "corrective" else
            f"Título: {req.problem_title}\n"
            f"Tipo: FRE\n"
        )
        content = (
            f"Título: {req.problem_title}\n"
            f"Tipo: {'NC' if req.recommended_action_type == 'corrective' else 'FRE'}\n"
            f"Descrição: {req.problem_desc}\n"
            f"Categoria: {req.problem_type} | Grupo: {req.problem_group}\n"
            f"Severidade: {req.risk_class}"
        )
        if req.nr_value is not None:
            content += f" | NR: {req.nr_value:.1f}"
        if req.pct_high_risk is not None:
            content += f" | % risco alto: {req.pct_high_risk:.0f}%"
        if req.worst_dimension:
            content += f"\nDimensão crítica: {req.worst_dimension}"
        if req.regulatory_basis:
            content += f"\nBase regulatória: {', '.join(req.regulatory_basis)}"
        if req.risk_factors:
            content += f"\nFatores de risco: {'; '.join(req.risk_factors)}"
        if req.plan_hint:
            content += f"\nDireção sugerida: {req.plan_hint}"
    else:
        # Fluxo legado — mantém compatibilidade com chamadas sem recommended_action_type
        tag = "problem"
        content = (
            f"{req.problem_desc}\n\n"
            f"Tipo: {req.problem_type} | Grupo: {req.problem_group}\n"
            f"Classificação: {req.risk_class}"
        )
        if req.nr_value is not None:
            content += f" | NR: {req.nr_value:.1f}"
        if req.pct_high_risk is not None:
            content += f" | % risco alto: {req.pct_high_risk:.0f}%"
        if req.worst_dimension:
            content += f"\nDimensão crítica: {req.worst_dimension}"

    prompt = f"<{tag}>\n{content}\n</{tag}>\n"

    if rag_ctx:
        prompt += f"\n<normative_context>\n{rag_ctx}\n</normative_context>\n"

    action_label = (
        "Gere plano de ação 5W2H corretivo imediato." if req.recommended_action_type == "corrective"
        else "Gere plano de ação 5W2H preventivo." if req.recommended_action_type == "preventive"
        else "Gere plano de ação 5W2H completo e específico."
    )
    prompt += f"\n{action_label}"
    return prompt


def _select_plan_system_prompt(recommended_action_type: str) -> str:
    """Seleciona o system prompt correto com base no tipo de plano solicitado."""
    if recommended_action_type == "corrective":
        return SYSTEM_PLAN_CORRECTIVE
    if recommended_action_type == "preventive":
        return SYSTEM_PLAN_PREVENTIVE
    return SYSTEM_PLAN  # legado


def _parse_analysis(raw: dict, model: str, rag_used: bool = False) -> AnalysisResponse:
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
        rag_used=rag_used,
        model=model,
    )


def _parse_findings(raw: dict, model: str, rag_used: bool = False) -> FindingsResponse:
    findings: list[NonConformity | EmergingRiskFactor] = []

    for f in raw.get("findings", []):
        finding_type = f.get("type", "")
        try:
            if finding_type == "NC":
                findings.append(
                    NonConformity(
                        id=f.get("id", ""),
                        type="NC",
                        category=f.get("category", ""),
                        group=f.get("group", ""),
                        severity=f.get("severity", "significant"),
                        nr_value=float(f.get("nr_value", 0.0)),
                        pct_high_risk=float(f.get("pct_high_risk", 0.0)),
                        worst_dimension=f.get("worst_dimension", ""),
                        title=f.get("title", ""),
                        description=f.get("description", ""),
                        regulatory_basis=f.get("regulatory_basis", []),
                        recommended_action_type="corrective",
                        urgency=f.get("urgency", "immediate"),
                        plan_hint=f.get("plan_hint", ""),
                    )
                )
            elif finding_type == "FRE":
                findings.append(
                    EmergingRiskFactor(
                        id=f.get("id", ""),
                        type="FRE",
                        category=f.get("category", ""),
                        group=f.get("group", ""),
                        severity=f.get("severity", "moderate"),
                        nr_value=float(f.get("nr_value", 0.0)),
                        pct_high_risk=float(f.get("pct_high_risk", 0.0)),
                        worst_dimension=f.get("worst_dimension", ""),
                        title=f.get("title", ""),
                        description=f.get("description", ""),
                        regulatory_basis=f.get("regulatory_basis", []),
                        risk_factors=f.get("risk_factors", []),
                        recommended_action_type="preventive",
                        urgency=f.get("urgency", "planned"),
                        plan_hint=f.get("plan_hint", ""),
                    )
                )
            else:
                log.warning("Finding com type desconhecido ignorado: %s", finding_type)
        except Exception as e:
            log.warning("Finding inválido ignorado: %s — %s", f.get("id"), e)

    raw_summary = raw.get("summary", {})
    nc_list = [f for f in findings if f.type == "NC"]
    fre_list = [f for f in findings if f.type == "FRE"]
    critical_nc = sum(1 for f in nc_list if f.severity == "critical")

    summary = FindingsSummary(
        total_findings=len(findings),
        nc_count=len(nc_list),
        fre_count=len(fre_list),
        critical_nc=critical_nc,
        model=model,
    )

    return FindingsResponse(findings=findings, summary=summary, rag_used=rag_used)


def _parse_plan(raw: dict, model: str) -> tuple[list[W5H2Action], PDCAStep]:
    if "action_plan" in raw:
        actions_raw = raw["action_plan"]
        pdca_raw    = raw.get("pdca", {})
    elif "acoes" in raw:
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
    provider = get_llm_provider()
    log.info("Agente HSE-IT iniciado — provider: %s | modelo: %s",
             type(provider).__name__, provider.model_name)
    yield
    log.info("Agente HSE-IT encerrado")


app = FastAPI(
    title="Agente HSE-IT",
    description="API de análise psicossocial, identificação de achados (NC/FRE) e geração de planos 5W2H + PDCA",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────────
@app.get("/health")
def health():
    provider = get_llm_provider()
    return {"status": "ok", "provider": type(provider).__name__, "model": provider.model_name}


# ── Endpoint 1: Análise completa ────────────────────────────
@app.post("/insights/generate", response_model=AnalysisResponse)
def generate_insight(
    req: AnalysisRequest,
    _: bool = Depends(verify_secret),
):
    log.info("generate_insight: chart_key=%s campaign=%s", req.chart_key, req.campaign_name)
    provider = get_llm_provider()

    rag_ctx  = ""
    rag_used = False
    if req.use_rag:
        query    = f"{req.chart_label} riscos psicossociais {req.campaign_name}"
        rag_ctx  = _safe_rag(query)
        rag_used = bool(rag_ctx)

    user_prompt = _build_analysis_prompt(req, rag_ctx)
    try:
        raw = provider.complete_json(SYSTEM_ANALYSIS, user_prompt, max_tokens=4000)
    except json.JSONDecodeError as e:
        log.error("JSON parse error: %s", e)
        raise HTTPException(status_code=502, detail="Modelo retornou resposta inválida")
    except Exception as e:
        log.error("Provider error: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro no modelo: {e}")

    result = _parse_analysis(raw, provider.model_name, rag_used=rag_used)
    return result


# ── Endpoint 2: Identificação de achados NC + FRE ───────────
@app.post("/insights/findings", response_model=FindingsResponse)
def generate_findings(
    req: FindingsRequest,
    _: bool = Depends(verify_secret),
):
    """
    Analisa os dados da campanha e retorna uma lista priorizada de achados:
    - NC  (Não Conformidade): situação que já viola limiar — plano corretivo imediato
    - FRE (Fator de Risco Emergente): padrão preocupante — plano preventivo

    O Next.js armazena essa lista e usa o campo `recommended_action_type` de cada
    finding para alimentar a chamada subsequente ao /insights/action-plan.
    """
    log.info("generate_findings: campaign=%s", req.campaign_name)
    provider = get_llm_provider()

    rag_ctx  = ""
    rag_used = False
    if req.use_rag:
        query    = f"riscos psicossociais achados conformidade {req.campaign_name}"
        rag_ctx  = _safe_rag(query)
        rag_used = bool(rag_ctx)

    user_prompt = _build_findings_prompt(req, rag_ctx)
    try:
        raw = provider.complete_json(SYSTEM_FINDINGS, user_prompt, max_tokens=5000)
    except json.JSONDecodeError as e:
        log.error("JSON parse error em /insights/findings: %s", e)
        raise HTTPException(status_code=502, detail="Modelo retornou resposta inválida")
    except Exception as e:
        log.error("Provider error em /insights/findings: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro no modelo: {e}")

    result = _parse_findings(raw, provider.model_name, rag_used=rag_used)
    log.info(
        "findings gerados: total=%d NC=%d FRE=%d critical_nc=%d",
        result.summary.total_findings,
        result.summary.nc_count,
        result.summary.fre_count,
        result.summary.critical_nc,
    )
    return result


# ── Endpoint 3: Plano de ação para NC ou FRE específico ─────
@app.post("/insights/action-plan", response_model=ActionPlanResponse)
def generate_action_plan(
    req: ActionPlanRequest,
    _: bool = Depends(verify_secret),
):
    """
    Gera plano 5W2H + PDCA para um finding específico (NC ou FRE) ou problema genérico.

    O campo `recommended_action_type` determina qual system prompt é usado:
    - "corrective" → SYSTEM_PLAN_CORRECTIVE (NC: ações com deadline agressivo, foco em resolução)
    - "preventive"  → SYSTEM_PLAN_PREVENTIVE (FRE: barreiras preventivas, indicadores leading)
    - qualquer outro → SYSTEM_PLAN (legado, compatibilidade retroativa)
    """
    log.info(
        "generate_action_plan: group=%s class=%s action_type=%s",
        req.problem_group, req.risk_class, req.recommended_action_type,
    )
    provider = get_llm_provider()

    rag_ctx  = ""
    rag_used = False
    if req.use_rag:
        rag_ctx  = _safe_rag(req.problem_desc)
        rag_used = bool(rag_ctx)

    system_prompt = _select_plan_system_prompt(req.recommended_action_type)
    user_prompt   = _build_plan_prompt(req, rag_ctx)

    try:
        raw = provider.complete_json(system_prompt, user_prompt, max_tokens=3000)
    except json.JSONDecodeError as e:
        log.error("JSON parse error em /insights/action-plan: %s", e)
        raise HTTPException(status_code=502, detail="Modelo retornou resposta inválida")
    except Exception as e:
        log.error("Provider error em /insights/action-plan: %s", e)
        raise HTTPException(status_code=502, detail=f"Erro no modelo: {e}")

    actions, pdca = _parse_plan(raw, provider.model_name)
    return ActionPlanResponse(
        action_plan=actions,
        pdca=pdca,
        recommended_action_type=req.recommended_action_type,
        rag_used=rag_used,
        model=provider.model_name,
    )
