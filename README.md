# AgentHive

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/react-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)

> [**Getting Started**](#getting-started) · [**Features**](#features) · [**Configuration**](#configuration) · [**Development**](#development) · [**Contributing**](CONTRIBUTING.md) · [**Roadmap**](#roadmap)

**A self-hosted command center for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — run multiple agents, monitor everything, and manage your projects from your phone.**

AgentHive is not a replacement for the Claude Code CLI. It's a companion. Keep using `claude` in your terminal the way you always have. AgentHive adds a layer on top: sync your CLI sessions to the web, run multiple agents in parallel, and manage everything from a single dashboard — including from your phone while you're away from your desk.

## Why AgentHive?

### Zero Migration Cost

Already using Claude Code? AgentHive plugs right in. It wraps the same `claude` CLI you already know — launched inside tmux sessions on your machine, managed through a web UI. Your existing workflow, CLAUDE.md files, and project setup all carry over. The only new dependencies are **tmux** (for session management) and optionally **Tailscale** (for secure remote access). No new APIs, no vendor lock-in, no relearning.

### Capture Ideas Anywhere

Walking your dog and had a breakthrough? Open AgentHive on your phone — dictate a task with voice input, type a quick note, or queue up a batch of ideas. Tasks land in your inbox and wait until you're ready to dispatch them. Stop losing ideas to "I'll remember it later."

### Global Monitoring

All your agents, all your projects, one screen. See which agents are running, which are waiting for input, and which just finished — in real time. WebSocket-powered live streaming shows agent output as it generates. Push notifications alert you when agents need attention, finish a task, or hit an error. A system monitor tracks disk, memory, and GPU usage. You always know what's happening.

### Multi-Agent Concurrency

Run 5, 10, or more Claude agents in parallel across different projects. Each agent gets its own isolated git worktree, so they never step on each other's code. The dispatcher manages global concurrency limits, queues messages when agents are busy, and handles timeouts and crash recovery automatically. Think of it as tabs for your AI workforce — switch between conversations, monitor progress, and keep everything moving.

### Session Management

Every agent conversation is persisted and resumable. Star important sessions for quick access. Browse session history across projects. AgentHive automatically backs up the SQLite database and caches session JSONL files incrementally. If an agent crashes mid-conversation, it recovers partial output and picks up where it left off. Your work is never lost.

### Project Memory

Each project carries its own CLAUDE.md context that agents read on every task. As you work, the context grows — coding conventions, past decisions, known gotchas. New agents inherit everything previous agents learned. AgentHive also syncs your existing CLI sessions, so conversations you had in the terminal are visible and searchable in the web UI.

## Features

| Category | What you get |
|---|---|
| **Agent Control** | Start, stop, resume agents. Choose model per agent (Opus/Sonnet/Haiku). Set timeouts and permission modes (supervised or autonomous). |
| **Chat Interface** | Rich markdown rendering (code blocks, tables, images). Plan mode with approve/reject. Interactive cards for tool confirmations. |
| **Mobile PWA** | Add to Home Screen on iOS/Android. Full functionality on mobile — voice input, push notifications, task management. |
| **CLI Session Sync** | Import and live-tail your terminal Claude Code sessions. Read-only — never interferes with the CLI process. |
| **Voice Input** | Dictate tasks using speech-to-text (OpenAI Whisper). Great for quick ideas on mobile. |
| **Task Inbox** | Capture tasks as they come, organize by project, dispatch when ready. Drag to reorder priorities. |
| **Push Notifications** | Get notified when agents finish, need input, or error out. Supports Web Push and Telegram. Per-agent mute, global toggles, smart suppression. |
| **Git Integration** | View commit history, diffs, and branch status per project. Agents work in isolated worktrees. |
| **System Monitor** | Disk, memory, and GPU usage at a glance. Health checks for the backend and Claude CLI. |
| **Security** | Password auth with exponential-backoff rate limiting. Inactivity-based lock. HTTPS encryption. |
| **Backups** | Automatic database backups with configurable intervals. Session JSONL caching. Crash recovery with partial output salvage. |
| **Dark/Light Theme** | System-aware theme toggle. |

## How It Works

```
Your Phone / Browser
    |
    +-- AgentHive Frontend (React PWA, HTTPS)
    |     +-- WebSocket  <-- real-time agent output, status, permissions
    |     +-- REST API   <-- agent control, tasks, file uploads
    |
    +-- AgentHive Backend (FastAPI + Uvicorn)
          |
          +-- Agent Dispatcher
          |     +-- tmux sessions (one per agent)
          |     |     +-- claude CLI (the same CLI you use in your terminal)
          |     +-- Isolated git worktrees per agent
          |     +-- Permission manager (tool approve/deny)
          |     +-- Timeout & crash recovery
          |
          +-- Sync Engine (tails CLI JSONL files, read-only)
          |     +-- Hook integration (SessionStart/End, tool events)
          |
          +-- Push Notifications (Web Push / VAPID + Telegram)
          |
          +-- SQLite Database + Automatic Backups
```

AgentHive runs on your Linux machine (or any machine reachable over the network). It launches Claude Code CLI instances inside tmux sessions, streams their output to the web UI via WebSocket, and manages their lifecycle. You interact through the browser — from the same machine, from your laptop, or from your phone over Tailscale.

## Getting Started

### Prerequisites

- **Linux** host (Ubuntu 22.04+ recommended)
- **Node.js** 18+ and npm
- **Python** 3.11+
- **tmux** (usually pre-installed; `sudo apt install tmux` if not)
- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code`
- **Claude subscription** — Claude Max or Pro (uses your existing subscription, no separate API billing)
- **OpenAI API key** _(optional, for voice input)_

### Quick Start

```bash
# 1. Clone
git clone https://github.com/jyao97/AgentHive.git && cd AgentHive

# 2. Run automated setup (installs deps, creates venv, generates SSL certs)
chmod +x setup.sh && ./setup.sh

# 3. Configure
nano .env   # Set HOST_PROJECTS_DIR (required), optionally OPENAI_API_KEY

# 4. Start
./run.sh start
```

Open `https://<machine-ip>:3000` in your browser. Set a password on first visit.

On iPhone: Safari > Share > **Add to Home Screen** for a native app experience.

<details>
<summary><strong>Manual setup (without setup.sh)</strong></summary>

```bash
# Install system deps
sudo apt-get install -y python3 python3-pip python3-venv tmux
npm install -g @anthropic-ai/claude-code

# Set up Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r orchestrator/requirements.txt

# Install frontend deps
cd frontend && npm install && cd ..

# Create projects directory
mkdir -p ~/agenthive-projects

# Configure
cp .env.example .env
nano .env

# Generate SSL certs (needed for mobile mic access)
mkdir -p certs
LAN_IP=$(hostname -I | awk '{print $1}')
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/selfsigned.key -out certs/selfsigned.crt \
  -subj "/CN=agenthive" \
  -addext "subjectAltName=DNS:agenthive,DNS:localhost,IP:127.0.0.1,IP:${LAN_IP}"

# Start
./run.sh start
```

</details>

## Configuration

All settings live in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `HOST_PROJECTS_DIR` | _(required)_ | Absolute path to your projects directory |
| `MAX_CONCURRENT_WORKERS` | `5` | Max simultaneous agent processes |
| `MAX_IDLE_AGENTS` | `20` | Max idle agents kept alive |
| `TASK_TIMEOUT_SECONDS` | `1800` | Default agent timeout (30 min) |
| `CC_MODEL` | `claude-opus-4-6` | Default Claude model |
| `OPENAI_API_KEY` | — | OpenAI key for voice input _(optional)_ |
| `PORT` | `8080` | Backend API port |
| `FRONTEND_PORT` | `3000` | Frontend HTTPS port |
| `VAPID_PRIVATE_KEY` | — | Web Push private key _(optional)_ |
| `VAPID_PUBLIC_KEY` | — | Web Push public key _(optional)_ |
| `BACKUP_INTERVAL_HOURS` | `24` | Database backup interval |
| `MAX_BACKUPS` | `48` | Number of backups to retain |
| `AUTH_TIMEOUT_MINUTES` | `30` | Inactivity lock timeout |
| `DISABLE_AUTH` | — | Set to `1` to disable auth (dev/trusted networks only) |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for notifications _(optional)_ |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for notifications _(optional)_ |

## Remote Access with Tailscale

The easiest way to access AgentHive from your phone outside your LAN:

1. Install [Tailscale](https://tailscale.com) on your server and phone
2. `tailscale up` on both devices
3. Access AgentHive at `https://<tailscale-ip>:3000`

No port forwarding, no public exposure. Tailscale creates a secure WireGuard tunnel between your devices.

## Folder Layout

```
~/
├── AgentHive/                      <- This repo
│   ├── run.sh                      <- Launch script (systemd services)
│   ├── setup.sh                    <- First-time setup script
│   ├── orchestrator/               <- FastAPI backend
│   ├── frontend/                   <- React PWA (Vite + TailwindCSS)
│   ├── certs/                      <- SSL certificates
│   ├── project-configs/            <- Project registry
│   ├── data/                       <- SQLite database
│   ├── backups/                    <- Automatic database backups
│   ├── logs/                       <- Server and orchestrator logs
│   └── .env                        <- Configuration
│
└── agenthive-projects/             <- Your project repositories
    ├── my-web-app/
    ├── ml-pipeline/
    └── ...
```

## Development

```bash
# Clone and setup
git clone https://github.com/jyao97/AgentHive.git && cd AgentHive
python3 -m venv .venv && source .venv/bin/activate
pip install -r orchestrator/requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env

# Start in development mode
./run.sh start          # Backend (FastAPI) + Frontend (Vite dev server)

# Run tests
cd frontend && npx vitest run                          # Frontend tests
cd orchestrator && python3 -m pytest tests/            # Backend tests

# Verify backend modules
cd orchestrator && python3 -c "from models import *; print('OK')"

# Build frontend for production
cd frontend && npx vite build

# View logs
./run.sh logs
```

### Project Structure

| Directory | Description |
|---|---|
| `orchestrator/` | FastAPI backend — routers, models, sync engine, agent dispatcher |
| `orchestrator/routers/` | API route handlers (agents, tasks, projects, auth, git, push) |
| `orchestrator/tests/` | Pytest test suite |
| `frontend/src/` | React 19 app — pages, components, hooks, contexts |
| `frontend/src/pages/` | Main views (Agents, Chat, Projects, Inbox, Git, Settings) |
| `project-configs/` | Per-project YAML registry and config files |

## Updating

```bash
cd AgentHive
git pull origin main
source .venv/bin/activate
pip install -r orchestrator/requirements.txt   # Update backend deps
cd frontend && npm install && cd ..            # Update frontend deps
./run.sh restart
```

AgentHive uses SQLite — database migrations are handled automatically on startup when the schema changes. Your data and configuration are preserved across updates.

## Troubleshooting

**Can't access from phone?**
Make sure port 3000 is open (`sudo ufw allow 3000`). Accept the self-signed certificate in your browser (tap "Advanced" > "Proceed").

**Agent fails to start?**
Check `logs/orchestrator.log`. Usually an expired OAuth token — run `claude setup-token` again.

**Voice input not working?**
Microphone requires HTTPS. Make sure you're accessing via `https://` and have valid SSL certs.

**Rate limited?**
Claude Max has usage limits. Reduce `MAX_CONCURRENT_WORKERS` or switch to a smaller model (Sonnet/Haiku).

**"Address already in use"?**
Another process is using the port. Kill it: `lsof -ti:8080 | xargs kill`

## Installing the CA Certificate

AgentHive uses a self-signed SSL certificate. Your server trusts it after setup, but other devices will show a browser warning until you install the cert.

**Download the cert** from another machine:
```bash
scp user@server-ip:~/AgentHive/certs/selfsigned.crt ~/agenthive.crt
```

<details>
<summary><strong>iPhone / iPad</strong></summary>

1. AirDrop or email `selfsigned.crt` to your device
2. Open the file — "Profile Downloaded" prompt appears
3. **Settings > General > VPN & Device Management** > tap the profile > **Install**
4. **Settings > General > About > Certificate Trust Settings** > toggle full trust for "agenthive"
</details>

<details>
<summary><strong>Android</strong></summary>

1. Transfer `selfsigned.crt` to the device
2. **Settings > Security > Encryption & credentials > Install a certificate > CA certificate**
3. Select the file and confirm
</details>

<details>
<summary><strong>macOS</strong></summary>

```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain agenthive.crt
```
</details>

<details>
<summary><strong>Windows</strong></summary>

```powershell
certutil -addstore "Root" agenthive.crt
```
</details>

<details>
<summary><strong>Linux (other machines)</strong></summary>

```bash
sudo cp agenthive.crt /usr/local/share/ca-certificates/agenthive.crt
sudo update-ca-certificates
```
</details>

After installing, restart your browser.

## Security

AgentHive is designed for self-hosted, single-user or trusted-network deployments.

| Layer | Implementation |
|---|---|
| **Authentication** | Password with SHA-256 hashing. Exponential backoff rate limiting (locks after 5 failed attempts, up to 1-hour lockout). |
| **Session Management** | JWT tokens with 24-hour server expiry + configurable inactivity timeout (default 30 min). |
| **Encryption** | All traffic over HTTPS (self-signed or custom cert). OAuth tokens stored in `.env`, never exposed to agents. |
| **Agent Isolation** | Each agent runs in its own tmux session with a dedicated git worktree. Configurable permission modes: supervised (every tool call requires approval) or autonomous. Read-only tools (Read, Glob, Grep, WebSearch) are always auto-approved. |
| **Process Safety** | Agents run as host subprocesses with configurable timeouts. Global concurrency limits prevent resource starvation. |
| **Backups** | Automatic periodic backups (SQLite + project configs + PROGRESS.md files). Path traversal validation on imports. |

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Reporting bugs and suggesting features
- Setting up a development environment
- Running tests and submitting pull requests

## Roadmap

Planned improvements (contributions welcome):

- [ ] **Docker deployment** — one-command setup via Docker Compose
- [ ] **Multi-user support** — role-based access for teams
- [ ] **Additional LLM providers** — support for non-Anthropic models
- [ ] **Plugin system** — extensible agent capabilities
- [ ] **Improved mobile experience** — native-feeling gestures and offline support

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
