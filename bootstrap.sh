#!/usr/bin/env bash
# Paste THIS into the Claude Code remote container's "Setup script" / startup field.
# It only pulls the cc-stack CLI from public GitHub and runs it; all real work
# (and all `claude mcp add` / `claude plugin install` calls) lives in the CLI.
#
# Secrets go in the container's Environment variables panel (NOT in this repo):
#   NVIDIA_API_KEY       (required)  MemoryOS LLM + embeddings via NVIDIA NIM
#   TAVILY_API_KEY       (optional)  enables the Tavily web-search MCP
#   CONTEXT7_API_KEY     (optional)  higher rate limits for Context7 (works without)
#   CLOUDFLARE_API_TOKEN (optional)  enables the Cloudflare API MCP without browser OAuth
set -uo pipefail
: "${CC_STACK_REPO:=https://github.com/GAIn-Tech/cc-stack}"
: "${CC_STACK_REF:=main}"
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
uv tool install --force "git+${CC_STACK_REPO}@${CC_STACK_REF}" \
  || uv tool install --force --from "git+${CC_STACK_REPO}@${CC_STACK_REF}" cc-stack
export PATH="$HOME/.local/bin:$PATH"
exec cc-stack "${1:-bootstrap}"
