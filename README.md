# AgentBridge

AgentBridge is a generic bridge for connecting OneBot-compatible chat platforms to an agent runtime. It is designed for communities that want an agent to behave less like a command bot and more like a trusted maintainer: it can answer direct messages, respond when mentioned, occasionally review ambient group context, and act through controlled platform tools.

The first supported adapter targets NapCat/OneBot 11 and an OpenAI-compatible agent server, but the architecture is intentionally split so other chat platforms and agent runtimes can be added later.

## Core Ideas

AgentBridge separates three responsibilities that are often mixed together in bots:

- Deterministic operations: authentication, admin commands, GitHub Actions dispatch, audit-friendly control flow.
- Agent handoff: deciding when to wake the agent and packaging the current event, recent context, unread ambient context, and archive file paths.
- Skill API: giving the agent a controlled way to call OneBot/NapCat, group moderation, and project status APIs.

The bridge stores chat history as durable files and indexes, but it does not try to become a semantic memory system. Deep reading, project understanding, summarization, and decision-making belong to the agent.

```text
Chat platform
  ↓
NapCat / OneBot
  ↓
AgentBridge
  ├─ deterministic command layer
  ├─ state and message archive layer
  ├─ agent handoff scheduler
  └─ skill API for controlled side effects
        ↑
        ↓
Agent runtime with installed skill
```

## Features

- OneBot 11 webhook ingestion for group and private messages.
- OpenAI-compatible agent handoff with `stream: false`.
- Immediate handoff for private messages, mentions, replies to the bot, and configured keywords.
- Ambient group mode using Poisson-style random checks instead of fixed hourly polling.
- JSONL message archive files for long-context agent reading.
- SQLite message index for bridge-internal lookup such as `message_id` resolution.
- Short-lived `agent_run` records with tool and target scope.
- Controlled skill API for QQ messaging, OneBot actions, group management, and GitHub status.
- Deterministic admin commands for GitHub release/deploy workflows.
- Hermes/OpenClaw-style skill package under `hermes_skill/`.
- Systemd service example.

## Architecture

### Deterministic Layer

The deterministic layer does not call the LLM. It handles actions that should be predictable and easy to audit:

- Admin authentication by platform user ID.
- GitHub workflow dispatch for release and deploy.
- Public status commands.
- Group configuration commands.
- Health checks.

High-risk write actions such as release, deploy, merge, and repository configuration should stay here instead of being exposed as general-purpose agent tools.

### Agent Handoff Layer

The bridge wakes the agent in two modes:

- Immediate: private chat, mention, reply to bot, keyword hit.
- Ambient: ordinary group messages are buffered, then delivered to the agent when the scheduler randomly checks the group.

Ambient scheduling uses an exponential distribution with a configurable mean. With the default mean of 3600 seconds, the agent behaves more like someone occasionally checking a chat app than a bot firing on a fixed cron boundary.

Each handoff includes:

- `agent_run_id`
- run mode
- allowed tools
- expiry time
- current trigger message
- recent group context or unread ambient batch
- JSONL archive paths for deeper history

### State Layer

AgentBridge stores state in simple local files by default:

```text
STATE_PATH=data/state.json
MESSAGE_STORE_PATH=data/messages.sqlite3
MESSAGE_ARCHIVE_DIR=data/message_archive
```

Message archives are written as JSONL:

```text
data/message_archive/groups/<group_id>/YYYY-MM-DD.jsonl
data/message_archive/private/<user_id>/YYYY-MM-DD.jsonl
```

The agent can read these archive files directly with its own file tools. AgentBridge intentionally does not expose context search skills; it only provides current handoff context and reliable archives.

### Skill API Layer

The installed agent skill calls AgentBridge instead of calling NapCat directly. AgentBridge then executes the real platform API request.

The skill API requires:

- `QQBRIDGE_SKILL_TOKEN`
- `run_id` in every request

The token proves the call came from the configured agent environment. The `run_id` scopes the call to a short-lived handoff.

The current implementation still keeps a lightweight policy gate:

- run existence and expiry
- allowed tool
- target group/repo
- maximum tool calls per run
- OneBot action allowlist level

This is deliberately simple. The trust model assumes the agent is a privileged maintainer assistant, while the bridge prevents accidental cross-target calls and keeps high-risk project writes in deterministic commands.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
```

Edit `.env` and `config.yaml` for your deployment.

Start the bridge:

```bash
qqbridge
```

By default the webhook endpoint is:

```text
http://0.0.0.0:8787/onebot
```

Point your NapCat HTTP client webhook to:

```text
http://127.0.0.1:8787/onebot
```

## Configuration

Common environment variables:

```text
QQBRIDGE_HOST=0.0.0.0
QQBRIDGE_PORT=8787
QQBRIDGE_WEBHOOK_PATH=/onebot
QQBRIDGE_WEBHOOK_TOKEN=
QQBRIDGE_SKILL_TOKEN=

NAPCAT_BASE_URL=http://127.0.0.1:3000
HERMES_BASE_URL=http://127.0.0.1:8642
HERMES_MODEL=hermes-agent

BOT_QQ_ID=
BOT_NAMES=bridge,bot
ADMIN_QQ_IDS=
ADMIN_PREFIX=。
PUBLIC_PREFIX=/

AMBIENT_ENABLED=true
AMBIENT_INTERVAL_SECONDS=3600
AMBIENT_MIN_UNREAD_MESSAGES=1
AMBIENT_MAX_UNREAD_MESSAGES=120
AMBIENT_JITTER_MIN_SECONDS=300
AMBIENT_JITTER_MAX_SECONDS=10800

SKILL_ONEBOT_LEVEL=group_admin

GITHUB_OWNER=
GITHUB_REPO=
GITHUB_RELEASE_WORKFLOW=release.yml
GITHUB_DEPLOY_WORKFLOW=deploy.yml
```

OneBot skill levels:

```text
chat        send_msg / send_group_msg
group_read  chat + group info/member read
group_admin group_read + delete_msg/card/ban/kick/admin/title/whole_ban
full        no OneBot action allowlist
```

## Commands

Public commands:

```text
/help
/ping
/forget
/status [workflow] [repo=alias] [branch=name]
/pr [repo=alias]
```

Admin commands:

```text
。release [ref] [repo=alias] [key=value...]
。deploy [ref] [repo=alias] [key=value...]
。repos
。group show
。group on
。group off
。group cooldown 120
。group keyword add release
。group keyword del release
。health
```

Admin command results for sensitive actions are sent privately when triggered from a group.

## GitHub Workflows

Release and deploy commands call GitHub Actions workflow dispatch:

```text
POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
```

Target workflows must support manual dispatch:

```yaml
on:
  workflow_dispatch:
    inputs:
      tag:
        required: false
        type: string
```

Example:

```text
。release main tag=v1.2.3
```

## Agent Skill

Install the skill package into your Hermes/OpenClaw skills directory:

```bash
mkdir -p ~/.hermes/skills/community
cp -R hermes_skill ~/.hermes/skills/community/agentbridge
```

Set the skill environment:

```bash
export QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
export QQBRIDGE_SKILL_TOKEN=<same value as QQBRIDGE_SKILL_TOKEN in AgentBridge>
```

Available skill endpoints include:

```text
POST /skills/onebot/call
POST /skills/qq/send_message
POST /skills/qq/reply_message
POST /skills/qq/send_face
POST /skills/qq/get_group_info
POST /skills/qq/get_group_member_info
POST /skills/qq/get_group_member_list
POST /skills/qq/set_group_card
POST /skills/qq/set_group_ban
POST /skills/qq/delete_msg
POST /skills/github/list_prs
POST /skills/github/get_pr
POST /skills/github/get_issue
POST /skills/github/get_workflow_status
```

The generic OneBot call endpoint is intended for methods that are not worth wrapping individually. The skill docs include links to NapCat and OneBot references.

## Development

Run tests:

```bash
pytest
```

Run a local health check:

```bash
qqbridge
curl http://127.0.0.1:8787/health
```

## Security Notes

- Do not commit `.env`, `data/`, or generated state files.
- Use a fine-grained GitHub token with only the required repository permissions.
- Keep release/deploy/merge in deterministic commands unless you have a stronger approval flow.
- Treat group moderation tools as privileged actions, even if the agent is trusted.
- Prefer running AgentBridge on the same host or private network as the agent runtime and NapCat.

## License

MIT
