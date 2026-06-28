# cc-stack

Headless bootstrap + self-heal for the Claude Code remote-container stack:

- **oh-my-claudecode (OMC)** — orchestration (subagents, `/team`, ultrawork). Installed + enabled via `claude plugin install`, configured via `omc setup`.
- **codebase-memory-mcp** — code knowledge graph; indexes the repo. Binary installed with `--skip-config`; registered via `claude mcp add`.
- **MemoryOS-MCP** — persistent persona memory (short/mid/long-term). Registered via `claude mcp add`; LLM + embeddings served by **NVIDIA NIM** (`nvidia/nemotron-3-ultra-550b-a55b` + `baai/bge-m3`).
- **headroom** — auto-compresses large tool outputs (reversible) as **hooks**, shipped in a generated plugin installed via `claude plugin install`. PostToolUse compress, SessionStart doctor, SessionEnd `learn`.

Plus three search/docs MCP integrations (all registered via `claude mcp add --transport http`, per the [official MCP docs](https://code.claude.com/docs/en/mcp)):

- **Context7** (Upstash) — up-to-date, version-specific library docs/code. Added at `https://mcp.context7.com/mcp`; `CONTEXT7_API_KEY` optional (works rate-limited without one).
- **Tavily** — web search/extract/crawl. Added at `https://mcp.tavily.com/mcp/?tavilyApiKey=…`; **requires `TAVILY_API_KEY`** headlessly (the OAuth alternative needs a browser), so it's skipped if the key is absent.
- **Cloudflare** — the public **docs** server `https://docs.mcp.cloudflare.com/mcp` (always), the **API** Code-Mode server `https://mcp.cloudflare.com/mcp` (only if `CLOUDFLARE_API_TOKEN` is set, avoiding browser OAuth), and the official **Cloudflare Skills** plugin (`claude plugin marketplace add cloudflare/skills`).

## Guarantee: no config-file guesswork

The CLI **never hand-edits** `.mcp.json`, `.claude/settings.json`, or `CLAUDE.md`. Every Claude change goes through the official CLI:

- MCP servers → `claude mcp add --scope user <name> -- cc-stack memoryos-launch` / `… -- codebase-memory-mcp`, and `claude mcp add --scope user --transport http <name> <url>` for Context7/Tavily/Cloudflare (flags before the name, per the docs)
- Plugins/hooks → `claude plugin marketplace add` + `claude plugin install` (OMC, and the generated `cc-stack-hooks` plugin)
- The operating mandate is injected each session via the SessionStart hook's `additionalContext` — not written to a file.

## Use

1. This repo is public at `github.com/GAIn-Tech/cc-stack` (the `bootstrap.sh` default points here). To use your own copy, fork it and set `CC_STACK_REPO`.
2. In your Claude Code remote environment:
   - **Environment variables** (this is where secrets live — never the repo): `NVIDIA_API_KEY=nvapi-…` (required). Optional: `TAVILY_API_KEY=tvly-…` (enables Tavily search), `CONTEXT7_API_KEY=…` (higher Context7 limits), `CLOUDFLARE_API_TOKEN=…` (enables the Cloudflare API MCP without OAuth), plus knobs like `CC_STACK_REPO`, `EMBED_PROVIDER`, `NIM_LLM_MODEL`.
   - **Network:** set to **All** (or allow `github.com`, `*.githubusercontent.com`, `huggingface.co`, `integrate.api.nvidia.com`, `registry.npmjs.org`, `pypi.org`, `mcp.context7.com`, `mcp.tavily.com`, `docs.mcp.cloudflare.com`, `mcp.cloudflare.com`).
   - **Setup script / startup command:** paste `bootstrap.sh` as-is (no edits needed unless you forked).
3. The setup script installs the CLI from the repo and runs `cc-stack bootstrap`. A SessionStart hook then runs `cc-stack doctor --hook` every session to validate + inject status before anything else.

## Commands

```
cc-stack bootstrap   # full: install + register (claude CLI) + omc setup + claude -p validate
cc-stack doctor      # idempotent repair + verify (manual)
cc-stack heal        # repair only
cc-stack validate    # claude -p smoke test (loads plugins/MCP, checks init)
cc-stack verify      # report-only (exit 1 if degraded)
cc-stack status      # print .gaintech/stack-state.json
```

Internal subcommands (used by the config we register, not run by hand): `hook-compress`, `hook-learn`, `memoryos-launch`.

## Notes

- Auto-compression uses `hookSpecificOutput.updatedToolOutput` (Claude Code ≥ v2.1.121). On older builds the hook degrades to passthrough (safe); `headroom learn` still runs.
- Heavier ML text compression: install with the `headroom-ai[all]` extra (pulls a ~2 GB model). Default is the lean build (JSON/log/code compression).
- Every failure is recorded with an explicit reason in `.gaintech/bootstrap.log` and `.gaintech/stack-state.json`.
- Integrations are optional and never fail the core stack: Tavily is skipped without `TAVILY_API_KEY`; the Cloudflare API server shows as `absent` until you complete OAuth via `/mcp` (unless `CLOUDFLARE_API_TOKEN` is set); the Cloudflare Skills plugin name may need a manual `/plugin install <name>@cloudflare` if auto-resolution misses. Disable all integrations with `--no-extras`.
- Changing `NIM_EMBED_MODEL` requires a fresh MemoryOS data dir (the data path is keyed to the embedding model).
