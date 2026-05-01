# AgentBridge for OneBot

让你的 Agent 住进 QQ 群。

AgentBridge 是一个 QQ/OneBot 11 的 Agent 接入后端。下层对接 NapCat 等 OneBot 11 兼容适配器，上层对接 Hermes、OpenClaw 或任何 OpenAI-compatible 的 Agent。

它不是命令机器人——Agent 会像真实群成员一样偶尔看一眼未读消息，自己决定要不要说话。

## 兼容性

**下层（OneBot 11 适配器）**
- NapCat
- LLOneBot
- 任何 OneBot 11 兼容实现

**上层（Agent）**
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)，附带开箱即用的 agentbridge skill
- [OpenClaw](https://github.com/openclaw/openclaw)
- 任何支持 OpenAI-compatible chat completions 的 Agent

## 快速开始

```bash
git clone https://github.com/AimesSoft/agentbridge-onebot.git
cd agentbridge-onebot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
agentbridge
```

NapCat HTTP Client 指向 `http://127.0.0.1:8787/onebot`。

完整配置和部署文档见 [docs/](docs/)。

## 许可证

MIT
