# AgentBridge for NipaPlay

AgentBridge 是为梨花（NipaPlay / NipaPlay-Reload）社区开发的智能 Agent 桥接层。它连接 NapCat / OneBot 11、Hermes Agent 和 GitHub，让一个受信任的 Agent 可以像项目维护者一样参与 QQ 群、处理私聊、随机查看群聊上下文、查询项目状态，并通过受控命令触发发布或部署流程。

这个项目的核心目标不是做一个传统命令机器人，而是给 NipaPlay 社区提供一个“维护者分身”：Bridge 负责接入、落盘、唤醒和真实副作用；Hermes Agent 负责理解、判断、阅读项目文件和长期上下文。

## 项目定位

AgentBridge 把三个容易混在一起的职责拆开：

- 硬逻辑层：管理员鉴权、确定性命令、GitHub Actions 触发、群配置、健康检查。
- Agent 转交层：判断什么时候唤醒 Hermes，并把当前消息、最近上下文、未读上下文和 JSONL 归档路径交给 Agent。
- Skill API 层：让 Hermes 通过受控 HTTP API 调用 OneBot/NapCat、QQ群管和 GitHub 状态工具。

Bridge 会保存聊天记录，但不会试图自己成为语义记忆系统。长上下文阅读、项目知识理解、总结和判断都交给 Hermes Agent 完成。

```text
QQ 群 / 私聊
  ↓
NapCat / OneBot 11
  ↓
AgentBridge
  ├─ 硬逻辑命令层
  ├─ 消息状态与 JSONL 归档层
  ├─ Agent handoff / ambient 调度层
  └─ Skill API 层
        ↑
        ↓
Hermes Agent + agentbridge skill
  ↓
NipaPlay 项目仓库 / 知识库 / GitHub API
```

## 当前能力

- 接收 NapCat / OneBot 11 群聊和私聊事件。
- 私聊、@bot、回复 bot、关键词命中会立即转交 Hermes。
- 普通群聊进入未读 buffer，由泊松式随机调度模拟“随机看手机”。
- 保存 SQLite 消息索引和 JSONL 消息归档，供 Hermes 自己用文件工具阅读长上下文。
- 为 Hermes 提供 QQ 发消息、回复、表情、私聊、群信息、群员信息、禁言、撤回、群名片等工具。
- 提供泛用 `onebot.call`，方便 Agent 使用不常见的 OneBot/NapCat API。
- 提供 GitHub PR、Issue、Workflow 状态查询。
- `release` / `deploy` 等高风险操作走确定性管理员命令，不直接交给 LLM 自由调用。
- 内置 Hermes skill 文档，包含 OneBot / NapCat 官方文档链接。
- 支持本机运行、systemd 运行和 Docker Compose 运行。

## 为什么为 NipaPlay 做这个

NipaPlay 的社区讨论里经常会出现构建、发布、播放器行为、平台兼容、Issue/PR 状态、用户反馈等上下文。传统 bot 只能响应命令，而 AgentBridge 的目标是让 Hermes Agent 能够：

- 像维护者一样读懂当前讨论。
- 在被 @ 或私聊时立刻回答。
- 在非紧急群聊里偶尔查看上下文，自主判断要不要参与。
- 需要时阅读 NipaPlay 仓库、知识库和聊天归档。
- 查询 GitHub PR、Issue、Workflow 状态。
- 在管理员明确命令下触发 release / deploy workflow。

## 架构

### 1. 硬逻辑层

硬逻辑层不调用 LLM，负责可审计、可预测的动作：

- 管理员 QQ 号鉴权。
- `/status`、`/pr` 等公开查询命令。
- `。release`、`。deploy` 等 GitHub Actions 触发命令。
- `。group on/off/cooldown/keyword` 等群配置命令。
- `。health` 健康检查。

高风险写操作，例如 release、deploy、merge、仓库配置修改，默认保留在这一层。

### 2. Agent Handoff 层

Bridge 在这些场景唤醒 Hermes：

- 私聊。
- 群里 @ bot。
- 回复 bot 的上一条消息。
- 命中配置关键词。
- ambient 随机查看群未读消息。

ambient 不是固定每小时 tick，而是指数分布随机等待，长期期望由 `AMBIENT_INTERVAL_SECONDS` 控制。默认 3600 秒，更像真人偶尔看群。

每次 handoff 会包含：

- `agent_run_id`
- run 模式：`private` / `immediate` / `ambient`
- 允许工具列表
- 过期时间
- 当前触发消息
- 最近群聊或未读消息批次
- JSONL 归档文件绝对路径

### 3. 状态与归档层

默认状态文件：

```text
STATE_PATH=data/state.json
MESSAGE_STORE_PATH=data/messages.sqlite3
MESSAGE_ARCHIVE_DIR=data/message_archive
```

消息归档路径：

```text
data/message_archive/groups/<group_id>/YYYY-MM-DD.jsonl
data/message_archive/private/<user_id>/YYYY-MM-DD.jsonl
```

Bridge 不提供复杂上下文搜索 skill。Hermes 如果需要更长历史，就直接读取这些 JSONL 文件。

### 4. Skill API 层

Hermes 通过安装的 `agentbridge` skill 调回 Bridge。Bridge 再调用 NapCat / OneBot 或 GitHub。

每个 skill 请求都需要：

- `QQBRIDGE_SKILL_TOKEN`
- 当前 handoff 提供的 `run_id`

Bridge 会检查 run 是否过期、工具是否允许、目标群/repo 是否匹配、调用次数是否超限，以及 `onebot.call` 是否符合 `SKILL_ONEBOT_LEVEL`。

OneBot 分级：

```text
chat        send_msg / send_group_msg
 group_read  chat + 群信息/群成员读取
 group_admin group_read + 撤回/改名片/禁言/踢人/管理员/全员禁言/头衔
full        不做 OneBot action allowlist
```

## 快速开始

完整服务器部署见 [部署指南](docs/deployment.md)。

```bash
git clone https://github.com/AimesSoft/agentbridge-onebot.git
cd agentbridge-onebot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
```

编辑 `.env` 和 `config.yaml` 后启动：

```bash
agentbridge
```

默认 webhook：

```text
http://127.0.0.1:8787/onebot
```

NapCat HTTP Client 指向这个地址即可。

## 关键配置

```text
QQBRIDGE_HOST=127.0.0.1
QQBRIDGE_PORT=8787
QQBRIDGE_WEBHOOK_PATH=/onebot
QQBRIDGE_WEBHOOK_TOKEN=<随机 token，可选>
QQBRIDGE_SKILL_TOKEN=<随机 token，Hermes skill 也要配置同一个>

NAPCAT_BASE_URL=http://127.0.0.1:3000
HERMES_BASE_URL=http://127.0.0.1:8642
HERMES_MODEL=hermes-agent

BOT_QQ_ID=<机器人 QQ 号>
BOT_NAMES=梨花,AgentBridge,bot
ADMIN_QQ_IDS=<管理员 QQ 号，逗号分隔>

AMBIENT_ENABLED=true
AMBIENT_INTERVAL_SECONDS=3600
AMBIENT_MAX_UNREAD_MESSAGES=120
SKILL_ONEBOT_LEVEL=group_admin

GITHUB_OWNER=AimesSoft
GITHUB_REPO=NipaPlay-Reload
GITHUB_RELEASE_WORKFLOW=release.yml
GITHUB_DEPLOY_WORKFLOW=deploy.yml
```

## 命令

公开命令：

```text
/help
/ping
/forget
/status [workflow] [repo=alias] [branch=name]
/pr [repo=alias]
```

管理员命令：

```text
。release [ref] [repo=alias] [key=value...]
。deploy [ref] [repo=alias] [key=value...]
。repos
。group show
。group on
。group off
。group cooldown 900
。group keyword add release
。group keyword del release
。health
```

敏感命令在群里触发时，回执会私聊给管理员。

## Hermes Skill

安装：

```bash
mkdir -p ~/.hermes/skills/community
cp -R hermes_skill ~/.hermes/skills/community/agentbridge
```

Hermes 运行环境需要：

```bash
export QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
export QQBRIDGE_SKILL_TOKEN=<与 AgentBridge .env 中一致>
```

Skill API 包括：

```text
POST /skills/onebot/call
POST /skills/qq/send_message
POST /skills/qq/send_private_message
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

## Docker 部署

仓库包含 `Dockerfile` 和 `docker-compose.yml`。当前 Docker 方案会在容器内启动 Hermes gateway 和 AgentBridge，并把 NipaPlay 仓库、知识库、Hermes runtime、消息数据挂载进容器。

基本流程：

```bash
cp .env.example .env
cp config.example.yaml config.yaml
# 准备 hermes-config.yaml、hermes-env、repos/NipaPlay-Reload、knowledge 等挂载内容
docker compose up -d --build
```

如果你只想让 AgentBridge 连接宿主机已有 Hermes，也可以不用 Docker，按部署指南使用 systemd。

## 开发

```bash
pytest
```

健康检查：

```bash
agentbridge
curl http://127.0.0.1:8787/health
```

## 安全说明

- 不要提交 `.env`、`config.yaml`、`data/`、`hermes-env`、`hermes-config.yaml`、`repos/`、`knowledge/`。
- GitHub token 建议使用 fine-grained PAT，仅授予目标仓库必要权限。
- release/deploy/merge 继续保留在确定性命令层，除非你实现了更强审批流程。
- 群管工具默认给可信 Agent 使用，但仍有 run_id、目标群和 OneBot 分级限制。

## 许可证

MIT
