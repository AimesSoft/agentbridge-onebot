---
name: agentbridge
description: Use when acting in OneBot/NapCat chat groups through AgentBridge. Provides messaging and group management plus GitHub project status; chat history is supplied as handoff context and JSONL archive file paths, not as context-search tools.
version: 0.1.0
author: AgentBridge contributors
license: MIT
metadata:
  hermes:
    tags: [qq, onebot, napcat, bridge, messaging, github]
required_environment_variables:
  - name: QQBRIDGE_SKILL_BASE_URL
    prompt: AgentBridge base URL
    help: Example: http://127.0.0.1:8787
    required_for: Calling AgentBridge skill APIs
  - name: QQBRIDGE_SKILL_TOKEN
    prompt: AgentBridge skill token
    help: Must match QQBRIDGE_SKILL_TOKEN configured in the AgentBridge server
    required_for: Authenticating to AgentBridge skill APIs
---

# QQ Bridge

## Overview

Hermes uses this skill to act through AgentBridge. AgentBridge stores QQ messages as files and includes current context plus JSONL archive paths in each handoff. If you need broad historical context, read those archive files with your file tools; do not ask AgentBridge to search or summarize context.

All QQ actions go through Bridge APIs. Do not access NapCat or OneBot directly.

Protocol references:

- NapCat API docs: https://napneko.github.io/develop/api/doc
- NapCat OneBot API docs: https://napneko.github.io/onebot/api
- OneBot 11 public API: https://github.com/botuniverse/onebot-11/blob/master/api/public.md

Required environment:

```bash
export QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
export QQBRIDGE_SKILL_TOKEN=<same token as AgentBridge>
```

Every request must include the `run_id` handed to you by AgentBridge in the current conversation context.

## When to Use

Use this skill when:

- Bridge handed off a QQ private, mention, reply, keyword, or ambient group conversation.
- You need to reply to a QQ message by `message_id`.
- You need to send a short QQ group message or built-in QQ face.
- You need OneBot/NapCat group info, member info, or group management through the bot admin account.
- You need PRs, issues, or GitHub Actions status for configured repositories.

Do not use this skill for release, deploy, merge, or repository configuration. Those remain AgentBridge hard commands.

## Bridge API

Base URL: `QQBRIDGE_SKILL_BASE_URL`, usually `http://127.0.0.1:8787`.

Authentication header:

```text
X-QQBridge-Skill-Token: <QQBRIDGE_SKILL_TOKEN>
```

### Generic OneBot Call

```text
POST /skills/onebot/call
{"run_id": "<run_id>", "action": "get_group_info", "params": {"group_id": 123}}
```

Allowed OneBot action scope is controlled by AgentBridge `SKILL_ONEBOT_LEVEL`:

```text
chat        send_msg / send_group_msg
group_read  chat + group info/member read
group_admin group_read + delete_msg/card/ban/kick/admin/title/whole_ban
full        no action allowlist
```

Use the helper-specific QQ endpoints for common actions. Use `onebot-call` when you need a less common OneBot/NapCat method from the references above.

Common useful OneBot actions:

```text
send_msg
send_group_msg
delete_msg
get_group_info
get_group_member_info
get_group_member_list
get_group_honor_info
set_group_card
set_group_ban
set_group_kick
set_group_admin
set_group_whole_ban
set_group_special_title
```

### Common QQ Helpers

```text
POST /skills/qq/send_message
{"run_id": "<run_id>", "group_id": "123", "text": "message"}

POST /skills/qq/send_private_message
{"run_id": "<run_id>", "user_id": "456", "text": "private message"}

POST /skills/qq/reply_message
{"run_id": "<run_id>", "message_id": "456", "text": "reply"}

POST /skills/qq/send_face
{"run_id": "<run_id>", "group_id": "123", "face_id": "14"}

POST /skills/qq/extend_group_attention
{"run_id": "<run_id>", "group_id": "123", "seconds": 60, "reason": "wait for logs"}
```

After you send a group message, AgentBridge automatically opens a short group attention window. If an active attention batch does not need an immediate reply but should keep listening for more context, call `extend_group_attention`.

### Group Tools

```text
POST /skills/qq/get_group_info
{"run_id": "<run_id>", "group_id": "123"}

POST /skills/qq/get_group_member_info
{"run_id": "<run_id>", "group_id": "123", "user_id": "456"}

POST /skills/qq/get_group_member_list
{"run_id": "<run_id>", "group_id": "123"}

POST /skills/qq/set_group_card
{"run_id": "<run_id>", "group_id": "123", "user_id": "456", "card": "new card"}

POST /skills/qq/set_group_ban
{"run_id": "<run_id>", "group_id": "123", "user_id": "456", "duration": 600}

POST /skills/qq/delete_msg
{"run_id": "<run_id>", "message_id": "789"}
```

### GitHub Status

```text
POST /skills/github/list_prs
{"run_id": "<run_id>", "repo": "default"}

POST /skills/github/get_pr
{"run_id": "<run_id>", "repo": "default", "number": 12}

POST /skills/github/get_issue
{"run_id": "<run_id>", "repo": "default", "number": 34}

POST /skills/github/get_workflow_status
{"run_id": "<run_id>", "repo": "default", "workflow": "release", "branch": "main", "limit": 5}
```

## Helper Commands

```bash
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py reply-message --run-id <run_id> --message-id 456 --text "我看一下这个 CI。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-message --run-id <run_id> --group-id 123 --text "release 状态我查到了。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-private-message --run-id <run_id> --user-id 456 --text "这是私聊回复。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-face --run-id <run_id> --group-id 123 --face-id 14
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py extend-group-attention --run-id <run_id> --group-id 123 --seconds 60 --reason "wait for logs"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py member-info --run-id <run_id> --group-id 123 --user-id 456
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py set-group-ban --run-id <run_id> --group-id 123 --user-id 456 --duration 60
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py onebot-call --run-id <run_id> --action get_group_info --params-json '{"group_id":123}'
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py workflow-status --run-id <run_id> --repo default --workflow release --limit 5
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py list-prs --run-id <run_id> --repo default
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py get-pr --run-id <run_id> --repo default --number 12
```

## Context

AgentBridge gives you:

- current trigger message
- recent group context
- unread ambient batch
- JSONL archive paths such as `/abs/path/data/message_archive/groups/<group_id>/YYYY-MM-DD.jsonl`

For deeper history, read those files yourself. AgentBridge intentionally does not provide context search skills.

## Common Pitfalls

1. Do not call QQ/NapCat/OneBot directly. Everything goes through AgentBridge.
2. Always pass the current `run_id`; never invent one.
3. Do not use this skill for release, deploy, merge, or destructive GitHub actions.
4. Keep QQ messages short and natural.
5. For ambient checks, reply only when useful.
6. Use group management tools with maintainer judgment.
