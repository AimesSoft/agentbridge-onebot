# 部署指南

这份指南面向 NipaPlay 社区的单机部署：NapCat、AgentBridge 和 Hermes Agent 都运行在同一台服务器上。Docker 和 systemd 二选一即可。

## 1. 前置条件

需要准备：

- Python 3.11+
- Git
- NapCat，且 OneBot HTTP API 可用
- Hermes Agent server，提供 OpenAI-compatible `/v1/chat/completions`
- 可选：GitHub fine-grained PAT，用于 release/deploy workflow dispatch
- 可选：NipaPlay-Reload 仓库和知识库目录，挂载给 Hermes 读取

## 2. 拉取代码

```bash
git clone https://github.com/AimesSoft/agentbridge-onebot.git
cd agentbridge-onebot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
```

## 3. 配置 `.env`

最小可用配置示例：

```text
QQBRIDGE_HOST=127.0.0.1
QQBRIDGE_PORT=8787
QQBRIDGE_WEBHOOK_PATH=/onebot
QQBRIDGE_WEBHOOK_TOKEN=<随机 webhook token，可选>
QQBRIDGE_SKILL_TOKEN=<随机 skill token，必须和 Hermes skill 一致>

NAPCAT_BASE_URL=http://127.0.0.1:3000
HERMES_BASE_URL=http://127.0.0.1:8642
HERMES_MODEL=hermes-agent
HERMES_SESSION_MAX_AGE_SECONDS=259200
HERMES_SESSION_MAX_HANDOFFS=200

BOT_QQ_ID=<机器人 QQ 号>
BOT_NAMES=梨花,AgentBridge,bot
ADMIN_QQ_IDS=<管理员 QQ 号，逗号分隔>

GITHUB_TOKEN=<可选 GitHub token>
GITHUB_OWNER=AimesSoft
GITHUB_REPO=NipaPlay-Reload
GITHUB_RELEASE_WORKFLOW=release.yml
GITHUB_DEPLOY_WORKFLOW=deploy.yml

GROUP_ATTENTION_ENABLED=true
GROUP_ATTENTION_TTL_SECONDS=180
GROUP_ATTENTION_BATCH_INTERVAL_SECONDS=8
GROUP_ATTENTION_MAX_BATCHES=8
GROUP_ATTENTION_MAX_EXTENSION_SECONDS=300
```

生成随机 token：

```bash
python - <<'PY'
import secrets
print("QQBRIDGE_WEBHOOK_TOKEN=" + secrets.token_urlsafe(32))
print("QQBRIDGE_SKILL_TOKEN=" + secrets.token_urlsafe(32))
PY
```

如果 NapCat 和 AgentBridge 在同机运行，建议 `QQBRIDGE_HOST=127.0.0.1`。如果要暴露到公网，请放在 HTTPS 反向代理后面。

Hermes session 生命周期参数：

- `HERMES_SESSION_MAX_AGE_SECONDS`：同一 QQ 对话线的 Hermes session 最长保留时间。默认 `259200`，也就是 3 天。
- `HERMES_SESSION_MAX_HANDOFFS`：同一 session 最多承载多少次 handoff。默认 `200`，防止活跃群在 3 天内堆出很长上下文。

任一条件达到后，AgentBridge 会在下一次调用 Hermes 前换一个新的 `X-Hermes-Session-Id`。这不会删除 SQLite/JSONL 消息归档，只是让 Hermes 从新的短上下文 session 开始。

## 4. 配置 `config.yaml`

示例：

```yaml
bot:
  qq_id: "<机器人 QQ 号>"
  names:
    - 梨花
    - AgentBridge
    - bot
  admins:
    - "<管理员 QQ 号>"

github:
  default_repo: default
  repos:
    default:
      owner: AimesSoft
      repo: NipaPlay-Reload
      default_ref: main
      workflows:
        release: release.yml
        deploy: deploy.yml
        ci: ci.yml

groups:
  "<QQ群号>":
    autonomous_enabled: true
    min_seconds_between_replies: 900
    keywords:
      - NipaPlay
      - 梨花
      - release
      - workflow
      - 构建
      - 发版
```

`autonomous_enabled` 只控制 ambient 自主看群。私聊、@bot、回复 bot 不受这个开关影响。

群级注意力窗口由 `GROUP_ATTENTION_*` 控制：有人 @bot 或回复 bot 时会立即唤醒 Hermes，并打断当前群已有的注意力窗口。Bridge 不会因为 Hermes 发群消息就自动进入注意力状态；只有 Hermes 显式调用 `qq.extend_group_attention` 后，窗口内普通群消息才会入队。固定窗口结束后再打包交给 Hermes 判断要不要继续回复。关闭 ambient 时，这个机制仍然可用。

注意力窗口参数含义：

- `GROUP_ATTENTION_ENABLED`：是否启用 agent 主动保持注意力机制。
- `GROUP_ATTENTION_BATCH_INTERVAL_SECONDS`：固定收集窗口时长。agent 调用 `qq.extend_group_attention` 后，Bridge 收集这段时间内的群消息，到点投喂 Hermes。
- `GROUP_ATTENTION_TICK_SECONDS`：后台检查注意力窗口是否到期的频率。
- `GROUP_ATTENTION_TTL_SECONDS`：注意力窗口安全过期时间，用于清理异常残留状态。
- `GROUP_ATTENTION_MAX_BATCHES`：单个注意力窗口最多拆分投喂多少批，防止异常刷屏。
- `GROUP_ATTENTION_MAX_BATCH_MESSAGES`：每批最多交给 Hermes 的消息数。
- `GROUP_ATTENTION_MAX_BUFFER_MESSAGES`：窗口内最多缓存多少条消息。
- `GROUP_ATTENTION_MAX_EXTENSION_SECONDS`：agent 单次调用 `qq.extend_group_attention` 能请求的最长观察时间。

## 5. 配置 NapCat

NapCat HTTP API 默认应在：

```text
http://127.0.0.1:3000
```

NapCat HTTP Client 上报地址配置为：

```text
POST http://127.0.0.1:8787/onebot
```

如果设置了 `QQBRIDGE_WEBHOOK_TOKEN`，并且 NapCat 支持自定义 header，请加：

```text
X-QQBridge-Token: <QQBRIDGE_WEBHOOK_TOKEN>
```

如果 NapCat 不方便加 header，就保持 AgentBridge 只监听 localhost 或内网，并把 `QQBRIDGE_WEBHOOK_TOKEN` 留空。

## 6. 安装 Hermes Skill

把 skill 放到 Hermes skills 目录：

```bash
mkdir -p ~/.hermes/skills/community
cp -R hermes_skill ~/.hermes/skills/community/agentbridge
```

Hermes 运行环境需要：

```text
QQBRIDGE_SKILL_BASE_URL=http://127.0.0.1:8787
QQBRIDGE_SKILL_TOKEN=<与 AgentBridge .env 中一致>
```

安装后重启 Hermes。下一次 session 中 Hermes 应能看到 `agentbridge` skill。

## 7. 手动运行

```bash
source .venv/bin/activate
agentbridge
```

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

期望返回：

```json
{"status":"ok","service":"agentbridge"}
```

## 8. systemd 运行

创建系统用户：

```bash
sudo useradd --system --home /opt/agentbridge --shell /usr/sbin/nologin agentbridge
```

把项目放到 `/opt/agentbridge`，配置好 `.env`、`config.yaml` 后：

```bash
sudo cp deploy/qqbridge.service.example /etc/systemd/system/agentbridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now agentbridge
```

查看日志：

```bash
sudo journalctl -u agentbridge -f
```

## 9. Docker Compose 运行

仓库包含 `Dockerfile` 和 `docker-compose.yml`。当前 Docker 方案会同时启动 Hermes gateway 和 AgentBridge。

准备：

```bash
cp .env.example .env
cp config.example.yaml config.yaml
mkdir -p data hermes-runtime/sessions hermes-runtime/logs hermes-runtime/cache hermes-runtime/runtime repos knowledge
```

需要额外准备并按 `docker-compose.yml` 挂载：

```text
hermes-config.yaml
hermes-env
repos/NipaPlay-Reload
knowledge/
```

启动：

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f agentbridge
```

如果你的 Hermes 已经在宿主机独立部署，可以不用 Docker，改用 systemd 方式。

## 10. 烟雾测试

公开命令：

```text
/ping
/status
/pr
```

管理员命令：

```text
。health
。group show
。group on
。group cooldown 900
```

触发 release：

```text
。release main tag=v1.2.3
```

这要求 GitHub token 有目标仓库 Actions 写权限，且 workflow 支持 `workflow_dispatch`。

## 11. 数据备份

需要备份：

```text
.env
config.yaml
data/state.json
data/messages.sqlite3
data/message_archive/
hermes-runtime/
```

不要发布：

```text
.env
config.yaml
data/
hermes-env
hermes-config.yaml
repos/
knowledge/
```

## 12. 常见问题

### AgentBridge health 正常，但 QQ 不回复

检查：

- NapCat webhook 地址是否正确。
- `BOT_QQ_ID` 是否是机器人 QQ 号。
- NapCat 上报 message 里是否包含 `self_id`。
- 群里是否真的 @ 到机器人，或配置了正确的 `BOT_NAMES`。
- Hermes `/health` 是否正常。
- AgentBridge 日志是否有 Hermes 请求报错。

### Skill 调用 401

`QQBRIDGE_SKILL_TOKEN` 在 AgentBridge 和 Hermes 运行环境中不一致。

### Skill 调用 403

可能原因：

- `run_id` 过期。
- Agent 调用了当前 run 不允许的工具。
- Agent 试图操作别的群或别的 repo。
- `SKILL_ONEBOT_LEVEL` 不允许该 OneBot action。

### release/deploy 失败

检查：

- `GITHUB_TOKEN` 是否配置。
- token 是否有 Actions write 权限。
- workflow 是否支持 `workflow_dispatch`。
- `config.yaml` 中 workflow alias 是否正确。

### ambient 不发言

这是正常行为。ambient 的原则是“随机看手机，可回可不回”。检查：

- 群是否 `。group on`。
- 是否有未读消息进入 buffer。
- cooldown 是否过长。
- Hermes 是否返回了 skip。

### @bot 后续追问看不到

检查 `GROUP_ATTENTION_ENABLED=true`，并确认 Hermes 在回复后显式调用了 `qq.extend_group_attention`。这个机制独立于 ambient：Agent 主动保持注意力后，后续群消息会在固定窗口内批量送给 Hermes，而不是要求群友每句话都重新 @。
