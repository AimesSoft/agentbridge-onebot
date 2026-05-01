# Architecture

AgentBridge is a platform bridge for chat-native agents. It is not a monolithic bot framework and it is not an agent memory system. Its job is to connect events, persist context, wake the agent, and execute authorized side effects.

## System Boundary

```text
Chat platform
  ↓ webhook/events
OneBot adapter
  ↓
AgentBridge
  ├─ deterministic layer
  ├─ state/archive layer
  ├─ handoff layer
  └─ skill API layer
        ↑
        ↓
Agent runtime
```

The current implementation supports:

- NapCat as the OneBot-compatible platform adapter.
- An OpenAI-compatible agent server.
- A Hermes/OpenClaw-style skill package.
- GitHub REST API integration for project status and workflow dispatch.

## Layers

### Deterministic Layer

This layer is used for operations that should not depend on model judgment:

- Admin command parsing.
- Admin user authentication.
- GitHub release/deploy workflow dispatch.
- Public GitHub status commands.
- Group configuration.
- Health checks.

This layer does not call the agent.

### Handoff Layer

This layer decides when to call the agent and how to package context.

Immediate triggers:

- Private message.
- Mention.
- Reply to a previous bot message.
- Configured keyword.

Ambient triggers:

- Normal group messages are appended to an unread buffer.
- A background scheduler samples the next check time from an exponential distribution.
- The long-term expected interval is `AMBIENT_INTERVAL_SECONDS`.
- Empty buffers, disabled groups, and cooldown windows are skipped.

The bridge does not interpret whether a conversation is important. It only packages the current chat slice and lets the agent decide whether to respond.

### State and Archive Layer

The bridge persists:

- Recent conversation state for short agent history.
- Recent group windows for immediate handoff.
- Ambient unread buffers.
- Last bot message IDs for reply detection.
- Group configuration overrides.
- Short-lived agent runs.
- SQLite message index.
- JSONL message archive files.

The JSONL archive is the source of truth for long context:

```text
data/message_archive/groups/<group_id>/YYYY-MM-DD.jsonl
data/message_archive/private/<user_id>/YYYY-MM-DD.jsonl
```

Each handoff includes recent context and the relevant archive paths. The agent can read those files with its own tools when it needs more history.

### Skill API Layer

The agent acts by calling AgentBridge skill APIs. AgentBridge then calls OneBot/NapCat or GitHub.

Current skill API groups:

- `onebot.call`: generic OneBot action call with level-based allowlist.
- `qq.*`: common helpers for messages, replies, faces, group info, and group moderation.
- `github.*`: read-only PR, issue, and workflow status tools.

Context search is intentionally not a skill. Deep context retrieval belongs to the agent runtime and its file tools.

## Agent Run Model

Every handoff creates an `agent_run`:

```text
run_id
mode: immediate / ambient / private
group_id
user_id
trigger_message_id
allowed_tools
allowed_repos
expires_at
max_tool_calls
tool_calls
```

Every skill request must include `run_id`. AgentBridge checks:

- The run exists and has not expired.
- The requested tool is in `allowed_tools`.
- The target group or repo matches the run.
- The run has not exceeded its tool call budget.
- Generic OneBot calls match `SKILL_ONEBOT_LEVEL`.

This is a practical safety boundary, not a full sandbox.

## OneBot Levels

`SKILL_ONEBOT_LEVEL` controls the generic `onebot.call` endpoint:

```text
chat        send_msg / send_group_msg
group_read  chat + group info/member read
group_admin group_read + delete_msg/card/ban/kick/admin/title/whole_ban
full        no OneBot action allowlist
```

Common actions have dedicated helper endpoints because they are easier for the agent to use correctly. Less common OneBot/NapCat methods can go through `onebot.call`.

## Message Flow

### Immediate Mention

```text
group message mentioning bot
  ↓
persist message
  ↓
create agent_run
  ↓
build context package
  ↓
call agent
  ↓
agent calls qq.reply_message or onebot.call
  ↓
AgentBridge validates run and target
  ↓
NapCat send_msg
```

### Ambient Check

```text
normal group messages
  ↓
append unread buffer and archive files
  ↓
Poisson-style scheduler wakes
  ↓
skip if no unread / disabled / cooldown
  ↓
create ambient agent_run
  ↓
send unread batch and archive paths to agent
  ↓
agent returns skip or structured actions
  ↓
AgentBridge sends messages and clears unread buffer
```

## External Interfaces

NapCat to AgentBridge:

```text
POST /onebot
```

AgentBridge to NapCat:

```text
POST <NAPCAT_BASE_URL>/<onebot_action>
```

AgentBridge to agent runtime:

```text
POST <HERMES_BASE_URL>/v1/chat/completions
GET  <HERMES_BASE_URL>/health
```

Agent skill to AgentBridge:

```text
POST /skills/*
```

AgentBridge to GitHub:

```text
GET  /repos/{owner}/{repo}/pulls
GET  /repos/{owner}/{repo}/pulls/{number}
GET  /repos/{owner}/{repo}/issues/{number}
GET  /repos/{owner}/{repo}/actions/runs
GET  /repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs
POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
```

## Design Principles

- Keep the bridge mechanical.
- Let the agent reason.
- Persist raw context before trying to summarize it.
- Prefer files for long context.
- Keep high-risk project writes deterministic.
- Give trusted agents useful platform tools, but keep target scoping and expiry.
