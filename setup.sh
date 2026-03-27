#!/usr/bin/env bash
set -euo pipefail

# AgentHive — First-time setup script
# Run once after cloning: chmod +x setup.sh && ./setup.sh

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; }

echo ""
echo "  ==============================="
echo "       AgentHive Setup"
echo "  ==============================="
echo ""

# --- Check system dependencies ---
MISSING=()
command -v python3 >/dev/null 2>&1 || MISSING+=("python3")
command -v tmux    >/dev/null 2>&1 || MISSING+=("tmux")
command -v node    >/dev/null 2>&1 || MISSING+=("nodejs")
command -v npm     >/dev/null 2>&1 || MISSING+=("npm")
command -v openssl >/dev/null 2>&1 || MISSING+=("openssl")

if [ ${#MISSING[@]} -gt 0 ]; then
    warn "Missing dependencies: ${MISSING[*]}"
    read -rp "  Install now? [Y/n] " REPLY
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip python3-venv tmux
        info "System dependencies installed"
    else
        error "Please install missing dependencies and re-run setup.sh"
        exit 1
    fi
fi

# --- Check Claude Code CLI ---
if ! command -v claude >/dev/null 2>&1; then
    warn "Claude Code CLI not found"
    read -rp "  Install via npm? [Y/n] " REPLY
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        npm install -g @anthropic-ai/claude-code
        info "Claude Code CLI installed"
    else
        warn "Skipping — install later with: npm install -g @anthropic-ai/claude-code"
    fi
else
    info "Claude Code CLI found"
fi

# --- Python virtual environment ---
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    info "Python virtual environment created (.venv)"
else
    info "Python virtual environment already exists"
fi

source .venv/bin/activate
pip install -q -r orchestrator/requirements.txt
info "Python dependencies installed"

# --- Frontend dependencies ---
(cd frontend && npm install --silent 2>/dev/null)
info "Frontend dependencies installed"

# --- Configuration ---
if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Created .env from .env.example"
    warn "Edit .env to set HOST_PROJECTS_DIR (required)"
else
    info ".env already exists"
fi

# --- Projects directory ---
DEFAULT_PROJECTS_DIR="$HOME/agenthive-projects"
if [ ! -d "$DEFAULT_PROJECTS_DIR" ]; then
    mkdir -p "$DEFAULT_PROJECTS_DIR"
    info "Created projects directory: $DEFAULT_PROJECTS_DIR"
else
    info "Projects directory exists: $DEFAULT_PROJECTS_DIR"
fi

# --- SSL certificates ---
if [ ! -f "certs/selfsigned.crt" ]; then
    mkdir -p certs
    LAN_IP=$(hostname -I | awk '{print $1}')
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout certs/selfsigned.key -out certs/selfsigned.crt \
        -subj "/CN=agenthive" \
        -addext "subjectAltName=DNS:agenthive,DNS:localhost,IP:127.0.0.1,IP:${LAN_IP}" \
        2>/dev/null
    info "SSL certificates generated (certs/)"

    if [ -d "/usr/local/share/ca-certificates" ]; then
        read -rp "  Trust the certificate system-wide? [Y/n] " REPLY
        if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
            sudo cp certs/selfsigned.crt /usr/local/share/ca-certificates/agenthive.crt
            sudo update-ca-certificates 2>/dev/null
            info "Certificate trusted system-wide"
        fi
    fi
else
    info "SSL certificates already exist"
fi

echo ""
echo "  ======================================="
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. Edit .env — set HOST_PROJECTS_DIR"
echo "    2. Run:  ./run.sh start"
echo "    3. Open: https://localhost:3000"
echo "  ======================================="
echo ""
