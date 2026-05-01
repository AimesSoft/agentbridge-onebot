# Deployment Guide

This guide describes a single-host deployment where NapCat, AgentBridge, and the agent runtime run on the same server.

## 1. Prepare Runtime

Requirements:

- Python 3.11+
- Git
- A running NapCat OneBot HTTP API
- A running OpenAI-compatible agent server
- Optional: GitHub token for release/deploy commands

Clone and install:

```bash
git clone https://github.com/AimesSoft/agentbridge-onebot.git
cd agentbridge-onebot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
```

## 2. Configure `.env`

Minimum useful configuration:

```text
QQBRIDGE_HOST=127.0.0.1
QQBRIDGE_PORT=8787
QQBRIDGE_WEBHOOK_PATH=/onebot
QQBRIDGE_WEBHOOK_TOKEN=<random-webhook-token>
QQBRIDGE_SKILL_TOKEN=<random-skill-token>

NAPCAT_BASE_URL=http://127.0.0.1:3000
HERMES_BASE_URL=http://127.0.0.1:8642
HERMES_MODEL=hermes-agent

BOT_QQ_ID=<bot-account-id>
BOT_NAMES=bridge,agent,bot
ADMIN_QQ_IDS=<your-platform-user-id>

GITHUB_TOKEN=<optional-github-token>
GITHUB_OWNER=<owner>
GITHUB_REPO=<repo>
```

Generate tokens locally:

```bash
python - <<'PY'
import secrets
print("QQBRIDGE_WEBHOOK_TOKEN=" + secrets.token_urlsafe(32))
print("QQBRIDGE_SKILL_TOKEN=" + secrets.token_urlsafe(32))
PY
```

For public internet exposure, put AgentBridge behind a reverse proxy with HTTPS. For same-host deployments, keep it bound to `127.0.0.1` and let NapCat call it locally.

## 3. Configure `config.yaml`

Example:

```yaml
bot:
  qq_id: "<bot-account-id>"
  names:
    - bridge
    - agent
  admins:
    - "<your-platform-user-id>"

github:
  default_repo: default
  repos:
    default:
      owner: "<owner>"
      repo: "<repo>"
      default_ref: main
      workflows:
        release: release.yml
        deploy: deploy.yml
        ci: ci.yml

groups:
  "<group-id>":
    autonomous_enabled: true
    min_seconds_between_replies: 900
    keywords:
      - release
      - workflow
      - build
```

`autonomous_enabled` controls ambient group participation. Mentions, replies, and private messages still work independently.

## 4. Configure NapCat

NapCat HTTP API should be reachable at:

```text
http://127.0.0.1:3000
```

Configure NapCat HTTP client webhook:

```text
POST http://127.0.0.1:8787/onebot
```

If `QQBRIDGE_WEBHOOK_TOKEN` is set, add this header in the NapCat HTTP client configuration if supported:

```text
X-QQBridge-Token: <QQBRIDGE_WEBHOOK_TOKEN>
```

If your NapCat setup cannot send custom headers, either keep AgentBridge on localhost/private network or leave `QQBRIDGE_WEBHOOK_TOKEN` empty.

## 5. Install Agent Skill

Install the bundled skill into the agent runtime:

```bash
mkdir -p ~/.hermes/skills/community
cp -R hermes_skill ~/.hermes/skills/community/agentbridge
```

Set these environment variables in the agent runtime service:

```text
QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
QQBRIDGE_SKILL_TOKEN=<same value as AgentBridge QQBRIDGE_SKILL_TOKEN>
```

Restart the agent runtime after installing the skill.

## 6. Run Manually

```bash
source .venv/bin/activate
agentbridge
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Expected:

```json
{"status":"ok","service":"agentbridge"}
```

## 7. Run With systemd

Create a dedicated user if desired:

```bash
sudo useradd --system --home /opt/agentbridge --shell /usr/sbin/nologin agentbridge
```

Install the project under `/opt/agentbridge`, then adapt the service file:

```bash
sudo cp deploy/qqbridge.service.example /etc/systemd/system/agentbridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now agentbridge
```

Check logs:

```bash
sudo journalctl -u agentbridge -f
```

## 8. Smoke Tests

Public command in chat:

```text
/ping
```

Admin health command:

```text
。health
```

GitHub status:

```text
/status
```

Ambient mode:

```text
。group on
。group cooldown 900
```

Then let normal group messages accumulate. The scheduler checks randomly with long-term mean `AMBIENT_INTERVAL_SECONDS`.

## 9. Data and Backups

Back up:

```text
data/state.json
data/messages.sqlite3
data/message_archive/
config.yaml
.env
```

Do not publish `.env` or `data/`.

## 10. Troubleshooting

Bridge health is ok but no chat response:

- Check NapCat webhook URL.
- Check the bot account ID in `BOT_QQ_ID`.
- Check mention parsing and bot names.
- Check AgentBridge logs.

Skill call fails with 401:

- `QQBRIDGE_SKILL_TOKEN` differs between AgentBridge and the agent runtime.

Skill call fails with 403:

- The `run_id` expired.
- The agent tried to call a tool outside the current group/repo.
- `SKILL_ONEBOT_LEVEL` is too restrictive for that OneBot action.

GitHub release/deploy fails:

- `GITHUB_TOKEN` is missing or lacks Actions write permission.
- The workflow does not support `workflow_dispatch`.
- The workflow alias in `config.yaml` does not match the command.
