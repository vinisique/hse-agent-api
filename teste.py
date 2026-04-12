"""
test_api.py — Testa os endpoints do Agente HSE-IT
Rodar: python test_api.py
"""

import json
import requests

BASE_URL = "http://localhost:8001"
API_SECRET = "mude aqui mesmo valor do encrypt key env"  # mesmo valor do .env

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_SECRET}",
}

CAMPAIGN_DATA = {
    "igrp": 5.14,
    "igrp_label": "Moderado",
    "workers_high_risk_pct": 100,
    "workers_critical_pct": 100,
    "dimension_analysis": [
        {"key": "demandas",              "name": "Demandas",              "nr": 16, "nr_label": "Crítico",    "avg_score": 3.63},
        {"key": "controle",              "name": "Controle",              "nr": 1,  "nr_label": "Aceitável",  "avg_score": 3.33},
        {"key": "apoio_chefia",          "name": "Apoio da Chefia",       "nr": 1,  "nr_label": "Aceitável",  "avg_score": 3.20},
        {"key": "apoio_colegas",         "name": "Apoio dos Colegas",     "nr": 1,  "nr_label": "Aceitável",  "avg_score": 3.25},
        {"key": "relacionamentos",       "name": "Relacionamentos",       "nr": 9,  "nr_label": "Importante", "avg_score": 3.00},
        {"key": "cargo",                 "name": "Cargo/Função",          "nr": 4,  "nr_label": "Aceitável",  "avg_score": 3.00},
        {"key": "comunicacao_mudancas",  "name": "Comunicação e Mudanças","nr": 4,  "nr_label": "Aceitável",  "avg_score": 3.00},
    ],
}


def print_section(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print('═' * 60)


# ── Health ───────────────────────────────────────────────────
def test_health():
    print_section("GET /health")
    r = requests.get(f"{BASE_URL}/health")
    print(f"Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))


# ── Endpoint 1: Análise completa ─────────────────────────────
def test_generate():
    print_section("POST /insights/generate")

    payload = {
        "chart_key":     "dimension_analysis",
        "chart_label":   "Análise por Dimensão HSE-IT",
        "chart_data":    CAMPAIGN_DATA,
        "campaign_name": "CampanhaDemo2",
        "use_rag":       False,  
    }

    r = requests.post(f"{BASE_URL}/insights/generate", json=payload, headers=HEADERS)
    print(f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"\nModelo: {data['model']}  |  RAG: {data['rag_used']}")
        print(f"\n--- ANÁLISE ---\n{data['analysis'][:300]}...")
        print(f"\n--- PROBLEMAS ({len(data['problems'])}) ---")
        for p in data["problems"]:
            print(f"  [{p['nivel_risco'].upper()}] {p['titulo']}")
        print(f"\n--- AÇÕES 5W2H ({len(data['action_plan'])}) ---")
        for a in data["action_plan"]:
            print(f"  {a['id']}: {a['what'][:80]}")
        print(f"\n--- PDCA ---")
        for fase, items in data["pdca"].items():
            print(f"  {fase.upper()}: {items[0] if items else '-'}")
    else:
        print(r.text)

    return r.json() if r.status_code == 200 else None


# ── Endpoint 2: Plano de ação específico ─────────────────────
def test_action_plan():
    print_section("POST /insights/action-plan")

    payload = {
        "problem_title":   "Sobrecarga crítica de Demandas",
        "problem_desc":    (
            "A dimensão Demandas apresenta NR 16 (Crítico), com 100% dos "
            "trabalhadores classificados em risco crítico. Avg score 3.63 indica "
            "alta percepção de sobrecarga e pressão no trabalho."
        ),
        "problem_type":    "Dimensão",
        "problem_group":   "Unidade Norte — Operações",
        "risk_class":      "Crítico",
        "nr_value":        16.0,
        "pct_high_risk":   100.0,
        "worst_dimension": "Demandas",
        "use_rag":         False,
    }

    r = requests.post(f"{BASE_URL}/insights/action-plan", json=payload, headers=HEADERS)
    print(f"Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"\nModelo: {data['model']}  |  RAG: {data['rag_used']}")
        print(f"\n--- AÇÕES 5W2H ({len(data['action_plan'])}) ---")
        for a in data["action_plan"]:
            print(f"\n  [{a['id']}]")
            print(f"    O quê:  {a['what']}")
            print(f"    Por quê:{a['why'][:80]}")
            print(f"    Quem:   {a['who']}")
            print(f"    Quando: {a['when']}")
            print(f"    Custo:  {a['how_much']}")
        print(f"\n--- PDCA ---")
        for fase, items in data["pdca"].items():
            print(f"  {fase.upper()}: {items[0] if items else '-'}")
    else:
        print(r.text)


if __name__ == "__main__":
    test_health()
    test_generate()
    test_action_plan()