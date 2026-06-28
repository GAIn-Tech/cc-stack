#!/usr/bin/env bash
# Paste THIS into the Claude Code remote container's "Setup script" / startup field.
#
# Why a tarball and not `git+https`? Claude Code on the web routes git through a
# proxy that is SCOPED TO THIS ENVIRONMENT'S CONFIGURED REPO, so `git clone` of any
# other repo (public or not) returns 403. Plain HTTPS to GitHub's CDN goes through
# the egress allowlist instead, so we fetch a tarball and install it locally.
#
# REQUIREMENT: allow the download host. In claude.ai -> Settings -> Capabilities ->
# "Code execution and file creation", set the domain allowlist to "All domains",
# or add: codeload.github.com  (PyPI is already allowed for dependencies).
#
# Secrets go in the Environment variables panel (NOT in any repo):
#   NVIDIA_API_KEY (required), TAVILY_API_KEY / CONTEXT7_API_KEY / CLOUDFLARE_API_TOKEN (optional).
set -uo pipefail
: "${CC_STACK_OWNER:=GAIn-Tech}"
: "${CC_STACK_NAME:=cc-stack}"
: "${CC_STACK_REF:=main}"
: "${CC_STACK_TARBALL:=https://codeload.github.com/${CC_STACK_OWNER}/${CC_STACK_NAME}/tar.gz/refs/heads/${CC_STACK_REF}}"

command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

tmp="$(mktemp -d)"
if curl -fsSL "$CC_STACK_TARBALL" | tar -xz -C "$tmp" 2>/dev/null; then
  dir="$(find "$tmp" -maxdepth 1 -type d -name "${CC_STACK_NAME}-*" | head -1)"
  uv tool install --force "$dir"
else
  # Fallback for normal machines / environments where git egress is open.
  uv tool install --force "git+https://github.com/${CC_STACK_OWNER}/${CC_STACK_NAME}@${CC_STACK_REF}" \
    || uv tool install --force --from "git+https://github.com/${CC_STACK_OWNER}/${CC_STACK_NAME}@${CC_STACK_REF}" cc-stack
fi

export PATH="$HOME/.local/bin:$PATH"
command -v cc-stack >/dev/null 2>&1 || { echo "cc-stack install failed -- check that codeload.github.com is allowlisted (or set All domains)"; exit 1; }
exec cc-stack "${1:-bootstrap}"
