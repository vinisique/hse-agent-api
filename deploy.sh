#!/bin/bash
# deploy.sh — Deploy da API HSE-IT no VPS Hostinger
# Uso: ./deploy.sh
# Pré-requisitos no VPS: Docker instalado, .env presente em ~/hse-agent-api/.env

set -e  # Para imediatamente se qualquer comando falhar

# ════════════════════════════════════════════════
# CONFIGURAÇÕES — ajuste conforme seu VPS
# ════════════════════════════════════════════════
VPS_USER="root"                          # usuário SSH do VPS
VPS_HOST="SEU_IP_HOSTINGER"             # IP do VPS na Hostinger
VPS_DIR="/root/hse-agent-api"           # diretório no VPS
CONTAINER_NAME="hse-agent-api"
IMAGE_NAME="hse-agent-api"
PORT="8001"

# ════════════════════════════════════════════════
# CORES para output legível
# ════════════════════════════════════════════════
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[aviso]${NC} $1"; }
fail() { echo -e "${RED}[erro]${NC} $1"; exit 1; }

# ════════════════════════════════════════════════
# 1. VALIDAÇÕES LOCAIS
# ════════════════════════════════════════════════
log "Verificando arquivos necessários..."
[ -f "Dockerfile" ]          || fail "Dockerfile não encontrado"
[ -f "main.py" ]             || fail "main.py não encontrado"
[ -f "prompts.py" ]          || fail "prompts.py não encontrado"
[ -f "rag.py" ]              || fail "rag.py não encontrado"
[ -f "llm_provider.py" ]     || fail "llm_provider.py não encontrado"
[ -f "requirements.prod.txt" ] || fail "requirements.prod.txt não encontrado"

# ════════════════════════════════════════════════
# 2. SINCRONIZA CÓDIGO PARA O VPS
# ════════════════════════════════════════════════
log "Enviando arquivos para o VPS..."
ssh "$VPS_USER@$VPS_HOST" "mkdir -p $VPS_DIR"

rsync -avz --progress \
  --exclude='.env' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='requirements.txt' \
  . "$VPS_USER@$VPS_HOST:$VPS_DIR/"

log "Código sincronizado."

# ════════════════════════════════════════════════
# 3. VERIFICA SE .env EXISTE NO VPS
# ════════════════════════════════════════════════
log "Verificando .env no VPS..."
ssh "$VPS_USER@$VPS_HOST" "[ -f $VPS_DIR/.env ]" || \
  fail ".env não encontrado em $VPS_DIR/.env no VPS. Crie-o manualmente antes do deploy."

# ════════════════════════════════════════════════
# 4. BUILD DA IMAGEM NO VPS
# ════════════════════════════════════════════════
log "Buildando imagem Docker no VPS (pode demorar no primeiro build)..."
ssh "$VPS_USER@$VPS_HOST" "cd $VPS_DIR && docker build -t $IMAGE_NAME ."

log "Build concluído."

# ════════════════════════════════════════════════
# 5. PARA CONTAINER ANTIGO E SOBE O NOVO
# ════════════════════════════════════════════════
log "Parando container anterior (se existir)..."
ssh "$VPS_USER@$VPS_HOST" "docker stop $CONTAINER_NAME 2>/dev/null || true"
ssh "$VPS_USER@$VPS_HOST" "docker rm $CONTAINER_NAME 2>/dev/null || true"

log "Subindo novo container..."
ssh "$VPS_USER@$VPS_HOST" "docker run -d \
  --name $CONTAINER_NAME \
  --restart unless-stopped \
  --env-file $VPS_DIR/.env \
  -p $PORT:$PORT \
  $IMAGE_NAME"

# ════════════════════════════════════════════════
# 6. HEALTH CHECK
# ════════════════════════════════════════════════
log "Aguardando API inicializar..."
sleep 5

HEALTH=$(ssh "$VPS_USER@$VPS_HOST" "curl -s http://localhost:$PORT/health" 2>/dev/null || echo "")

if echo "$HEALTH" | grep -q '"status":"ok"'; then
  log "✅ Deploy concluído! API respondendo em http://$VPS_HOST:$PORT"
  echo "$HEALTH"
else
  warn "API ainda não respondeu. Verificando logs..."
  ssh "$VPS_USER@$VPS_HOST" "docker logs --tail 30 $CONTAINER_NAME"
  fail "Health check falhou. Verifique os logs acima."
fi
