---
name: agentbridge
description: 用于通过 AgentBridge 在 NipaPlay QQ 群和私聊中行动。提供 OneBot/NapCat 消息、QQ群管和 GitHub 项目状态能力；聊天历史通过 handoff 上下文和 JSONL 归档文件提供，而不是通过上下文搜索工具提供。
version: 0.1.0
author: AgentBridge contributors
license: MIT
metadata:
  hermes:
    tags: [qq, onebot, napcat, bridge, messaging, github, nipaplay]
required_environment_variables:
  - name: QQBRIDGE_SKILL_BASE_URL
    prompt: AgentBridge base URL
    help: 例如 http://127.0.0.1:8787
    required_for: 调用 AgentBridge Skill API
  - name: QQBRIDGE_SKILL_TOKEN
    prompt: AgentBridge skill token
    help: 必须和 AgentBridge 服务端配置的 QQBRIDGE_SKILL_TOKEN 一致
    required_for: 鉴权 AgentBridge Skill API
---

# AgentBridge Skill

## Overview

你通过这个 skill 代表 NipaPlay / 梨花社区在 QQ 中行动。所有 QQ / NapCat / OneBot 操作都必须经过 AgentBridge，不要直接访问 NapCat。

AgentBridge 会在每次 handoff 中给你：当前触发消息、最近群聊或未读批次、相关 JSONL 归档文件路径。需要更长上下文时，请使用你自己的文件工具读取这些 JSONL 文件；不要要求 AgentBridge 搜索或总结上下文。

协议参考：

- NapCat API 文档：https://napneko.github.io/develop/api/doc
- NapCat OneBot API 文档：https://napneko.github.io/onebot/api
- OneBot 11 public API：https://github.com/botuniverse/onebot-11/blob/master/api/public.md

运行环境：

```bash
export QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
export QQBRIDGE_SKILL_TOKEN=<与 AgentBridge 一致>
```

每次调用都必须带当前上下文中的 `run_id`。

## When to Use

在这些场景使用本 skill：

- AgentBridge 把 QQ 私聊、@bot、回复 bot、关键词或 ambient 群聊转交给你。
- 你需要回复某条 QQ 消息。
- 你需要发送群消息、私聊或 QQ 表情。
- 你需要读取群信息、群员信息或执行群管操作。
- 你需要查看 NipaPlay 仓库 PR、Issue、GitHub Actions 状态。

不要用这个 skill 触发 release、deploy、merge 或仓库配置修改。那些动作保留给 AgentBridge 的硬命令层。

## 鉴权

Base URL: `QQBRIDGE_SKILL_BASE_URL`

Header:

```text
X-QQBridge-Skill-Token: <QQBRIDGE_SKILL_TOKEN>
```

每个 payload 还必须带：

```json
{"run_id": "<当前 AgentBridge handoff 提供的 run_id>"}
```

## 泛用 OneBot 调用

```text
POST /skills/onebot/call
{"run_id": "<run_id>", "action": "get_group_info", "params": {"group_id": 123}}
```

`SKILL_ONEBOT_LEVEL` 控制可用 action：

```text
chat        send_msg / send_group_msg
group_read  chat + 群信息/群成员读取
group_admin group_read + 撤回/改名片/禁言/踢人/管理员/全员禁言/头衔
full        不做 OneBot action allowlist
```

常见 OneBot action：

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

常用动作优先使用下面的 helper；少见动作再走 `onebot-call`。

## 常用 QQ Helper

```text
POST /skills/qq/send_message
{"run_id": "<run_id>", "group_id": "123", "text": "message"}

POST /skills/qq/send_private_message
{"run_id": "<run_id>", "user_id": "456", "text": "private message"}

POST /skills/qq/reply_message
{"run_id": "<run_id>", "message_id": "456", "text": "reply"}

POST /skills/qq/send_face
{"run_id": "<run_id>", "group_id": "123", "face_id": "14"}
```

## 群工具

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

## GitHub 状态工具

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

## Helper 命令

```bash
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py reply-message --run-id <run_id> --message-id 456 --text "我看一下这个 CI。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-message --run-id <run_id> --group-id 123 --text "release 状态我查到了。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-private-message --run-id <run_id> --user-id 456 --text "这是私聊回复。"
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py send-face --run-id <run_id> --group-id 123 --face-id 14
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py member-info --run-id <run_id> --group-id 123 --user-id 456
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py set-group-ban --run-id <run_id> --group-id 123 --user-id 456 --duration 60
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py onebot-call --run-id <run_id> --action get_group_info --params-json '{"group_id":123}'
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py workflow-status --run-id <run_id> --repo default --workflow release --limit 5
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py list-prs --run-id <run_id> --repo default
python ${HERMES_SKILL_DIR}/scripts/qqbridge.py get-pr --run-id <run_id> --repo default --number 12
```

## 上下文

AgentBridge 会给你：

- 当前触发消息
- 最近群聊上下文
- ambient 未读批次
- JSONL 归档路径，例如 `/abs/path/data/message_archive/groups/<group_id>/YYYY-MM-DD.jsonl`
- NipaPlay 项目仓库和知识库路径，取决于部署挂载

更深历史请自己读文件。AgentBridge 不提供上下文搜索 skill。

## 注意事项

1. 不要直接调用 QQ/NapCat/OneBot，一切通过 AgentBridge。
2. 永远使用当前上下文提供的 `run_id`，不要编造。
3. 不要用 skill 触发 release、deploy、merge 或破坏性 GitHub 操作。
4. QQ 群消息要短、自然、像维护者。
5. ambient 场景不要刷存在感，没必要就不回复。
6. 群管工具可以用，但要按 NipaPlay 维护者判断谨慎使用。
