FROM python:3.11-slim

# System deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl git \
    && rm -rf /var/lib/apt/lists/*

# Install Hermes from GitHub
RUN pip install --no-cache-dir "hermes-agent @ git+https://github.com/NousResearch/hermes-agent.git@main"

# Install AgentBridge
WORKDIR /app
COPY pyproject.toml .
COPY qqbridge/ qqbridge/
RUN pip install --no-cache-dir .

# Install AgentBridge skill into Hermes
COPY hermes_skill/ /root/.hermes/skills/community/agentbridge/

# Config files will be mounted
RUN mkdir -p /app/data /root/.hermes

EXPOSE 8787 8642

# Entrypoint starts both Hermes gateway and AgentBridge
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
