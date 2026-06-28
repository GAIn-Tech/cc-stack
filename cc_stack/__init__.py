"""cc-stack: headless bootstrap + self-heal for the Claude Code memory /
orchestration / context stack. ALL Claude config changes go through the
`claude` CLI (`claude mcp add`, `claude plugin install`) -- this module never
hand-edits .mcp.json or settings.json. Hooks ship inside a generated local
plugin installed via `claude plugin install`."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path

def env(k, d): return os.environ.get(k, d)
def have(x): return shutil.which(x) is not None

HOME = Path.home()
def _git_root():
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        return r.stdout.strip() or None
    except Exception:
        return None
REPO_ROOT = Path(env("CLAUDE_PROJECT_DIR", "") or _git_root() or os.getcwd())
GAINTECH = REPO_ROOT / ".gaintech"
STATE_FILE = GAINTECH / "stack-state.json"
LOG_FILE = GAINTECH / "bootstrap.log"
SHARE = HOME / ".local/share/gaintech"
NPM_PREFIX = HOME / ".npm-global"
PLUGIN_DIR = SHARE / "cc-stack-plugin"
USER_SETTINGS = Path(env("CLAUDE_CONFIG_DIR", str(HOME / ".claude"))) / "settings.json"
GIT_HOOKS_DIR = SHARE / "githooks"

MEMOS_DIR = SHARE / "memoryos"
MEMOS_VENV = MEMOS_DIR / ".venv"
MEMOS_PY = MEMOS_VENV / "bin/python"
MEMOS_SERVER = MEMOS_DIR / "memoryos-mcp/server_new.py"
MEMOS_CFG = GAINTECH / "memoryos_config.json"

NIM_BASE_URL = env("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_LLM_MODEL = env("NIM_LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NIM_EMBED_MODEL = env("NIM_EMBED_MODEL", "baai/bge-m3")
NIM_EMBED_DIM = env("NIM_EMBED_DIM", "1024")
EMBED_PROVIDER = env("EMBED_PROVIDER", "nim")
NIM_API_KEY = env("NVIDIA_API_KEY", env("NIM_API_KEY", ""))
MEMOS_DATA = GAINTECH / ("memoryos_data_" + NIM_EMBED_MODEL.replace("/", "_"))
OMC_MARKETPLACE = env("OMC_MARKETPLACE", "https://github.com/Yeachan-Heo/oh-my-claudecode")
OMC_NPM_PKG = env("OMC_NPM_PKG", "oh-my-claude-sisyphus")
MIN_CHARS = int(env("HEADROOM_MIN_CHARS", "2000"))
IS_REMOTE = env("CLAUDE_CODE_REMOTE", "") == "true"
JS_PM = env("CC_STACK_JS_PM", "") or ("npm" if IS_REMOTE else ("bun" if have("bun") else "npm"))

STATE: dict[str, str] = {}
FAILURES: dict[str, str] = {}
DO = {"omc": True, "cbm": True, "memoryos": True, "headroom": True, "extras": True}
CORE = ["omc", "codebase-memory-mcp", "memoryos", "headroom"]
EXTRA = ["context7", "tavily", "cloudflare-docs", "cloudflare-api", "cloudflare-skills"]
MODE = "full"
_LOG = None
def logf():
    global _LOG
    if _LOG is None:
        GAINTECH.mkdir(parents=True, exist_ok=True)
        _LOG = open(LOG_FILE, "a")
    return _LOG
def log(m): print(f"[stack] {m}", file=sys.stderr)
def ok(m): print(f"[ ok ] {m}", file=sys.stderr)
def warn(m): print(f"[warn] {m}", file=sys.stderr)
def fail(comp, state, reason): STATE[comp] = state; FAILURES[comp] = reason; warn(f"{comp}: {reason}")

def run(label, *cmd, timeout=None, shell=False, stdin_null=False):
    f = logf(); f.write(f"\n=== {time.strftime('%H:%M:%S')} :: {label} ===\n"); f.flush()
    try:
        c = cmd[0] if shell else list(cmd)
        r = subprocess.run(c, shell=shell, stdout=f, stderr=f, timeout=timeout,
                           stdin=(subprocess.DEVNULL if stdin_null else None))
        if r.returncode != 0:
            warn(f"step failed [{label}] rc={r.returncode} -> {LOG_FILE}")
            FAILURES[f"step:{label}"] = f"exit {r.returncode} (see bootstrap.log)"
        return r.returncode
    except subprocess.TimeoutExpired:
        warn(f"step timeout [{label}]"); FAILURES[f"step:{label}"] = "timeout"; return 124
    except Exception as e:
        warn(f"step error [{label}]: {e}"); FAILURES[f"step:{label}"] = str(e); return 1

def cap(*cmd, timeout=None):
    try: return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
    except Exception: return None

def write_state():
    GAINTECH.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "remote": IS_REMOTE, "repo": str(REPO_ROOT), "log": str(LOG_FILE),
        "components": {k: STATE.get(k, "unknown") for k in CORE},
        "integrations": {k: STATE.get(k, "unknown") for k in EXTRA},
        "failures": FAILURES,
    }, indent=2))

# --------------------------------------------------------------------------
# deps + claude CLI helpers
# --------------------------------------------------------------------------
def apt(pkg):
    if not have("apt-get"): return False
    run(f"apt {pkg}", f"(sudo apt-get update -y || apt-get update -y) && (sudo apt-get install -y {pkg} || apt-get install -y {pkg})", shell=True)
    return have(pkg)

def ensure_deps():
    log(f"core deps (pm={JS_PM}, remote={IS_REMOTE})")
    for d in (SHARE, NPM_PREFIX / "bin", GAINTECH):
        d.mkdir(parents=True, exist_ok=True)
    have("git") or apt("git") or fail("core", "degraded", "git missing and apt failed")
    have("curl") or apt("curl")
    if not have("uv"):
        run("uv install", "curl -LsSf https://astral.sh/uv/install.sh | sh", shell=True)
        os.environ["PATH"] = f"{HOME}/.local/bin:{HOME}/.cargo/bin:" + os.environ.get("PATH", "")
    if have("npm"):
        run("npm prefix", "npm", "config", "set", "prefix", str(NPM_PREFIX))
    if JS_PM == "bun" and not have("bun"):
        run("bun install", "curl -fsSL https://bun.sh/install | bash", shell=True)
        os.environ["PATH"] = f"{HOME}/.bun/bin:" + os.environ.get("PATH", "")
    have("node") or warn("Node not found (preinstalled on the CC universal image; locally install Node 18+)")
    ef = env("CLAUDE_ENV_FILE", "")
    if ef:
        try:
            with open(ef, "a") as fh:
                fh.write(f"PATH={HOME}/.local/bin:{NPM_PREFIX}/bin:{HOME}/.bun/bin:$PATH\n")
                fh.write("CLAUDE_CODE_SYNC_PLUGIN_INSTALL=1\n")
        except Exception:
            pass

def claude_ok(): return have("claude")
def plugin_cli_ok():
    if not have("claude"): return False
    r = cap("claude", "plugin", "--help"); return bool(r and r.returncode == 0)
def mcp_present(name):
    r = cap("claude", "mcp", "get", name); return bool(r and r.returncode == 0)
def plugin_listed(substr):
    r = cap("claude", "plugin", "list"); return bool(r and substr.lower() in (r.stdout or "").lower())

def mcp_add(comp, name, *cmd):
    if mcp_present(name):
        ok(f"MCP '{name}' present"); return True
    if not claude_ok():
        fail(comp, "degraded", "claude CLI required to register MCP (no manual config editing)"); return False
    rc = run(f"claude mcp add {name}", "claude", "mcp", "add", "--scope", "user", name, "--", *cmd)
    if rc == 0 and mcp_present(name):
        ok(f"MCP '{name}' registered"); return True
    fail(comp, "degraded", f"`claude mcp add {name}` failed (see log)"); return False

def add_http_mcp(comp, name, url, header=None, required_note=None, fatal=False):
    if mcp_present(name):
        ok(f"MCP '{name}' present"); STATE[comp] = "ok"; return True
    if not claude_ok():
        (fail if fatal else _note)(comp, "claude CLI required to register MCP (no manual config editing)"); return False
    flags = ["claude", "mcp", "add", "--scope", "user", "--transport", "http"]
    if header:
        flags += ["--header", header]
    rc = run(f"claude mcp add {name}", *flags, name, url)
    if rc == 0 and mcp_present(name):
        ok(f"MCP '{name}' registered"); STATE[comp] = "ok"; return True
    (fail if fatal else _note)(comp, required_note or f"`claude mcp add {name}` failed (may need OAuth via /mcp or a key)")
    return False
def _note(comp, reason):
    # optional integration: record reason but don't count as a hard failure
    STATE[comp] = "degraded"; FAILURES[comp] = reason; warn(f"{comp}: {reason}")

# --------------------------------------------------------------------------
# 1) OMC
# --------------------------------------------------------------------------
def omc_enabled():
    return plugin_listed("oh-my-claude") or have("omc")
def install_omc():
    if not DO["omc"]: STATE["omc"] = "skipped"; return
    log("OMC: install + enable + configure (headless)")
    if not have("omc"):
        pkg = f"{OMC_NPM_PKG}@latest"
        run("omc cli", *(["bun", "add", "-g", pkg] if JS_PM == "bun" else ["npm", "install", "-g", pkg]))
    if plugin_cli_ok():
        run("omc marketplace", "claude", "plugin", "marketplace", "add", OMC_MARKETPLACE)
        for cand in ("oh-my-claudecode@omc", "oh-my-claudecode@oh-my-claudecode", "oh-my-claudecode"):
            if run(f"omc install {cand}", "claude", "plugin", "install", cand, "--scope", "project") == 0:
                ok(f"OMC plugin enabled: {cand}"); break
    else:
        warn("claude plugin CLI unavailable; OMC plugin not enabled")
    marker = GAINTECH / ".omc_setup_done"
    if have("omc") and (MODE == "full" or not marker.exists()):
        if run("omc setup", "omc", "setup", "--global", timeout=150, stdin_null=True) == 0 \
           or run("omc setup", "omc", "setup", timeout=150, stdin_null=True) == 0:
            ok("omc setup complete")
        else:
            warn("omc setup non-fatal (no active session for wizard); OMC is enabled")
        marker.touch()
    if omc_enabled(): STATE["omc"] = "ok"
    else: fail("omc", "degraded", "not enabled (check 'claude plugin list' / 'omc')")

# --------------------------------------------------------------------------
# 2) codebase-memory-mcp
# --------------------------------------------------------------------------
def install_cbm():
    if not DO["cbm"]: STATE["codebase-memory-mcp"] = "skipped"; return
    if not have("codebase-memory-mcp"):
        log("installing codebase-memory-mcp (binary only; --skip-config)")
        run("cbm install", "curl -fsSL https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh | bash -s -- --skip-config", shell=True)
        os.environ["PATH"] = f"{HOME}/.local/bin:" + os.environ.get("PATH", "")
    if not have("codebase-memory-mcp"):
        fail("codebase-memory-mcp", "missing", "install failed (GitHub releases blocked? see log)"); return
    r = cap("codebase-memory-mcp")
    run("cbm auto_index", "codebase-memory-mcp", "config", "set", "auto_index", "true")
    if env("CC_REINDEX", "") == "1" or not _cbm_indexed():
        log(f"indexing codebase: {REPO_ROOT}")
        run("cbm index", "codebase-memory-mcp", "cli", "index_repository", json.dumps({"repo_path": str(REPO_ROOT)}))
    if mcp_add("codebase-memory-mcp", "codebase-memory", "codebase-memory-mcp"):
        if STATE.get("codebase-memory-mcp") not in ("degraded", "missing"):
            STATE["codebase-memory-mcp"] = "ok"
def _cbm_indexed():
    r = cap("codebase-memory-mcp", "cli", "list_projects")
    return bool(r and str(REPO_ROOT) in (r.stdout or ""))

# --------------------------------------------------------------------------
# 3) MemoryOS (NIM backend) -- launched via `cc-stack memoryos-launch`
# --------------------------------------------------------------------------
MEMOS_SHIM = r'''
import os,sys,runpy,logging
logging.basicConfig(level=logging.INFO,format="[memoryos-nim] %(levelname)s %(message)s",stream=sys.stderr)
L=logging.getLogger("memoryos-nim")
BASE=os.environ.get("NIM_BASE_URL","https://integrate.api.nvidia.com/v1")
KEY=os.environ.get("NVIDIA_API_KEY") or os.environ.get("NIM_API_KEY")
EMB=os.environ.get("NIM_EMBED_MODEL","baai/bge-m3"); PROV=os.environ.get("EMBED_PROVIDER","nim").lower()
SRV=os.environ["MEMOS_SERVER"]; CFG=os.environ["MEMOS_CONFIG"]
try:
    from openai.resources.chat import completions as _c
    _o=_c.Completions.create
    def _p(self,*a,**k):
        try:
            if "nemotron" in str(k.get("model","")).lower():
                eb=dict(k.get("extra_body") or {}); ck=dict(eb.get("chat_template_kwargs") or {}); ck.setdefault("enable_thinking",False); eb["chat_template_kwargs"]=ck; k["extra_body"]=eb
        except Exception as e: L.warning("thinking passthrough %s",e)
        return _o(self,*a,**k)
    _c.Completions.create=_p; L.info("nemotron thinking off")
except Exception as e: L.warning("chat seam %s",e)
if PROV=="nim" and KEY:
    try:
        import sentence_transformers as st
        from openai import OpenAI
        cl=OpenAI(base_url=BASE,api_key=KEY); _e=st.SentenceTransformer.encode
        def _enc(self,s,*a,**k):
            one=isinstance(s,str); b=[s] if one else list(s)
            try:
                r=cl.embeddings.create(model=EMB,input=b); v=[d.embedding for d in r.data]
                try:
                    import numpy as np; arr=np.asarray(v,dtype="float32"); return arr[0] if one else arr
                except Exception: return v[0] if one else v
            except Exception as e:
                L.warning("nim embed %s -> local",e); return _e(self,s,*a,**k)
        st.SentenceTransformer.encode=_enc; L.info("encode -> NIM %s",EMB)
    except Exception as e: L.warning("embed seam %s -> local",e)
else:
    L.info("local embeddings (PROV=%s key=%s)",PROV,bool(KEY))
sys.argv=[SRV,"--config",CFG]; sys.path.insert(0,os.path.dirname(SRV))
runpy.run_path(SRV,run_name="__main__")
'''
def memoryos_launch():
    if not MEMOS_PY.exists() or not MEMOS_SERVER.exists():
        sys.stderr.write("memoryos not installed; run `cc-stack heal`\n"); sys.exit(1)
    e = dict(os.environ, MEMOS_SERVER=str(MEMOS_SERVER), MEMOS_CONFIG=str(MEMOS_CFG))
    os.execve(str(MEMOS_PY), [str(MEMOS_PY), "-c", MEMOS_SHIM], e)

def _memos_layers():
    return [L for L in ("short_term", "mid_term", "long_term") if list(MEMOS_DIR.rglob(f"{L}.py"))]
def install_memoryos():
    if not DO["memoryos"]: STATE["memoryos"] = "skipped"; return
    log("MemoryOS-MCP (persistent persona memory; NIM backend)")
    if not MEMOS_SERVER.exists():
        run("memoryos clone", "git", "clone", "--depth", "1", "https://github.com/BAI-LAB/MemoryOS.git", str(MEMOS_DIR))
    if not MEMOS_SERVER.exists():
        fail("memoryos", "missing", "clone failed (GitHub blocked? see log)"); return
    if not MEMOS_VENV.exists():
        run("memoryos venv", "uv", "venv", str(MEMOS_VENV), "--python", "3.11") or run("memoryos venv", "uv", "venv", str(MEMOS_VENV))
    run("memoryos deps", "uv", "pip", "install", "--python", str(MEMOS_PY), "-r", str(MEMOS_DIR / "memoryos-mcp/requirements.txt"))
    run("memoryos openai", "uv", "pip", "install", "--python", str(MEMOS_PY), "openai>=1.40", "sentence-transformers", "numpy")
    MEMOS_DATA.mkdir(parents=True, exist_ok=True)
    MEMOS_CFG.write_text(json.dumps({
        "user_id": env("MEMOS_USER_ID", "gaintech"), "assistant_id": env("MEMOS_ASSISTANT_ID", "claude-code"),
        "openai_api_key": NIM_API_KEY, "openai_base_url": NIM_BASE_URL, "llm_model": NIM_LLM_MODEL,
        "embedding_model_name": "BAAI/bge-m3", "data_storage_path": str(MEMOS_DATA),
    }, indent=2))
    if not NIM_API_KEY:
        fail("memoryos", "degraded", "NVIDIA_API_KEY not set -> wired but LLM/embedding calls fail until exported")
    layers = _memos_layers()
    if sorted(layers) == ["long_term", "mid_term", "short_term"]:
        ok(f"MemoryOS layers present: {' '.join(layers)}")
    else:
        fail("memoryos", "degraded", f"incomplete memory layers (need short+mid+long): {layers}")
    if run("memoryos import", str(MEMOS_PY), "-c", "import importlib;importlib.import_module('memoryos');print('ok')") != 0:
        fail("memoryos", "degraded", "memoryos package import failed (deps missing; see log)")
    mcp_add("memoryos", "memoryos", "cc-stack", "memoryos-launch")
    if mcp_present("memoryos") and STATE.get("memoryos") not in ("degraded", "missing"):
        STATE["memoryos"] = "ok"

# --------------------------------------------------------------------------
# 4) headroom -- context compression as HOOKS (shipped in the plugin below)
# --------------------------------------------------------------------------
def headroom_importable():
    try:
        import headroom  # noqa: F401
        return True
    except Exception:
        return False
def headroom_bin():
    p = Path(sys.executable).parent / "headroom"
    return str(p) if p.exists() else shutil.which("headroom")
def hook_compress():
    try: data = json.load(sys.stdin)
    except Exception: return
    if data.get("hook_event_name") != "PostToolUse": return
    out = data.get("tool_output")
    text = out if isinstance(out, str) else (json.dumps(out, ensure_ascii=False) if out is not None else "")
    if len(text) < MIN_CHARS: return
    try:
        from headroom import compress
        res = compress([{"role": "user", "content": text}], model=env("HEADROOM_MODEL", "gpt-4o"))
        msgs = getattr(res, "messages", None) or (res.get("messages") if isinstance(res, dict) else None)
        comp = None
        if msgs:
            c = msgs[-1].get("content") if isinstance(msgs[-1], dict) else None
            if isinstance(c, str): comp = c
            elif isinstance(c, list): comp = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        if not comp or len(comp) >= len(text): return
        saved = getattr(res, "tokens_saved", None) or (res.get("tokens_saved") if isinstance(res, dict) else None)
        note = f"\n\n[headroom: compressed{f', ~{saved} tokens saved' if saved else ''}; re-run tool for full detail]"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": comp + note}}))
    except Exception as e:
        sys.stderr.write(f"[headroom] passthrough: {e}\n")
def hook_learn():
    hb = headroom_bin()
    if not hb: sys.stderr.write("headroom not found; skip learn\n"); return
    try: subprocess.run([hb, "learn"], stdout=sys.stderr, stderr=sys.stderr, timeout=120)
    except Exception as e: sys.stderr.write(f"headroom learn skipped: {e}\n")

# --------------------------------------------------------------------------
# Hooks plugin (the ONLY way we touch hooks: claude plugin install)
# --------------------------------------------------------------------------
def install_hooks_plugin():
    if not plugin_cli_ok():
        fail("headroom", "degraded", "claude plugin CLI unavailable -> cannot install hooks without editing config"); return
    p = PLUGIN_DIR
    (p / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (p / "cc-stack-hooks/.claude-plugin").mkdir(parents=True, exist_ok=True)
    (p / "cc-stack-hooks/hooks").mkdir(parents=True, exist_ok=True)
    (p / ".claude-plugin/marketplace.json").write_text(json.dumps({
        "name": "cc-stack", "owner": {"name": "cc-stack"},
        "plugins": [{"name": "cc-stack-hooks", "source": "./cc-stack-hooks",
                     "description": "Auto context-compression + session doctor for the cc-stack"}],
    }, indent=2))
    (p / "cc-stack-hooks/.claude-plugin/plugin.json").write_text(json.dumps({
        "name": "cc-stack-hooks", "version": "0.1.0",
        "description": "headroom output compression + SessionStart doctor + SessionEnd learn",
        "author": {"name": "cc-stack"}, "hooks": "./hooks/hooks.json",
    }, indent=2))
    (p / "cc-stack-hooks/hooks/hooks.json").write_text(json.dumps({"hooks": {
        "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "cc-stack hook-compress", "timeout": 60}]}],
        "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "cc-stack doctor --hook", "timeout": 150}]}],
        "SessionEnd": [{"hooks": [{"type": "command", "command": "cc-stack hook-learn", "async": True}]}],
    }}, indent=2))
    run("plugin marketplace add", "claude", "plugin", "marketplace", "add", str(p))
    rc = run("plugin install hooks", "claude", "plugin", "install", "cc-stack-hooks@cc-stack", "--scope", "user")
    if rc == 0 and plugin_listed("cc-stack-hooks"):
        ok("hooks plugin installed (PostToolUse compress / SessionStart doctor / SessionEnd learn)")
    else:
        fail("headroom", "degraded", "`claude plugin install cc-stack-hooks` failed (see log)")

# --------------------------------------------------------------------------
# Extra MCP integrations (all via `claude mcp add` per official docs:
# https://code.claude.com/docs/en/mcp -- flags before name, --header for auth)
# --------------------------------------------------------------------------
def install_extra_mcps():
    if not DO["extras"]:
        for k in EXTRA:
            STATE[k] = "skipped"
        return
    log("extra MCPs: Context7 + Tavily + Cloudflare (claude mcp add) -- all enabled")

    # Context7 (Upstash) -- up-to-date library docs/code. Key optional (header if present).
    c7 = env("CONTEXT7_API_KEY", "")
    add_http_mcp("context7", "context7", "https://mcp.context7.com/mcp",
                 header=(f"CONTEXT7_API_KEY: {c7}" if c7 else None))

    # Tavily web search. With a key -> fully headless; without -> register the OAuth
    # endpoint so it's still enabled (one-time `/mcp` auth completes it). Never skipped.
    tv = env("TAVILY_API_KEY", "")
    tv_url = f"https://mcp.tavily.com/mcp/?tavilyApiKey={tv}" if tv else "https://mcp.tavily.com/mcp/"
    add_http_mcp("tavily", "tavily", tv_url,
                 required_note=("registered; complete one-time OAuth via /mcp" if not tv else None))

    # Cloudflare docs server -- public, no auth.
    add_http_mcp("cloudflare-docs", "cloudflare-docs", "https://docs.mcp.cloudflare.com/mcp")

    # Cloudflare API (Code Mode over the whole API). Token -> headless; else OAuth via /mcp.
    cf = env("CLOUDFLARE_API_TOKEN", "")
    add_http_mcp("cloudflare-api", "cloudflare-api", "https://mcp.cloudflare.com/mcp",
                 header=(f"Authorization: Bearer {cf}" if cf else None),
                 required_note=("registered; complete one-time OAuth via /mcp" if not cf else None))

    # Cloudflare Skills plugin (official agents recommendation): skills + slash commands.
    if plugin_cli_ok():
        run("cf skills marketplace", "claude", "plugin", "marketplace", "add", "cloudflare/skills")
        done = False
        for cand in ("cloudflare@cloudflare", "cloudflare-skills@cloudflare", "cloudflare"):
            if run(f"cf skills install {cand}", "claude", "plugin", "install", cand, "--scope", "user") == 0 and plugin_listed("cloudflare"):
                ok(f"cloudflare skills installed: {cand}"); STATE["cloudflare-skills"] = "ok"; done = True; break
        if not done:
            STATE["cloudflare-skills"] = "degraded"
            FAILURES["cloudflare-skills"] = "marketplace added; install name unresolved -> `/plugin install <name>@cloudflare`"
    else:
        STATE["cloudflare-skills"] = "degraded"
        FAILURES["cloudflare-skills"] = "claude plugin CLI unavailable"

# --------------------------------------------------------------------------
# Disable AI/Claude commit + PR attribution (off by default).
# Official setting (https://code.claude.com/docs/en/settings): attribution.commit/pr.
# Empty strings remove the "Co-Authored-By: Claude" trailer and the
# "Generated with Claude Code" PR footer. Supersedes the deprecated
# includeCoAuthoredBy boolean. No CLI exists for it -> idempotent merge of this one key.
# --------------------------------------------------------------------------
def disable_attribution():
    want = {"commit": "", "pr": ""}
    try:
        USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if USER_SETTINGS.exists():
            try:
                data = json.loads(USER_SETTINGS.read_text() or "{}")
            except Exception:
                data = {}
        if data.get("attribution") != want:
            data["attribution"] = want
            data.pop("includeCoAuthoredBy", None)  # deprecated; don't let it conflict
            USER_SETTINGS.write_text(json.dumps(data, indent=2))
        STATE["attribution"] = "off"
        ok("attribution OFF (no Co-Authored-By / no 'Generated with Claude Code' in commits or PRs)")
    except Exception as e:
        STATE["attribution"] = "unknown"
        warn(f"could not disable attribution: {e}")
    # Belt-and-suspenders: a commit-msg hook that strips any attribution lines that
    # slip through (Anthropic tracks the setting being intermittently ignored).
    # Non-destructive: only wired if no core.hooksPath is already set.
    try:
        cur = cap("git", "config", "--global", "--get", "core.hooksPath")
        already = (cur.stdout or "").strip() if cur and cur.returncode == 0 else ""
        if not already or already == str(GIT_HOOKS_DIR):
            GIT_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
            hook = GIT_HOOKS_DIR / "commit-msg"
            hook.write_text(
                "#!/usr/bin/env bash\n"
                "f=\"$1\"\n"
                "grep -viE '^(Co-Authored-By: Claude|.*Generated with .*Claude Code|🤖 Generated with)' "
                "\"$f\" > \"$f.tmp\" && mv \"$f.tmp\" \"$f\"\n"
            )
            os.chmod(hook, 0o755)
            run("git attribution scrubber", "git", "config", "--global", "core.hooksPath", str(GIT_HOOKS_DIR))
            ok("installed commit-msg attribution scrubber (global git hook)")
        else:
            warn(f"core.hooksPath already set to {already}; skipping scrubber (attribution setting still applies)")
    except Exception as e:
        warn(f"attribution scrubber not installed: {e}")


# --------------------------------------------------------------------------
# gitignore (not a Claude config; safe to write)
# --------------------------------------------------------------------------
def ensure_gitignore():
    gi = REPO_ROOT / ".gitignore"
    entries = ["# cc-stack (secrets, local memory data, logs)", ".gaintech/memoryos_config.json",
               ".gaintech/memoryos_data_*/", ".gaintech/stack-state.json", ".gaintech/bootstrap.log",
               ".gaintech/.omc_setup_done", "CLAUDE.local.md"]
    have_lines = set(gi.read_text().splitlines()) if gi.exists() else set()
    add = [e for e in entries if e not in have_lines]
    if add:
        with open(gi, "a") as fh: fh.write(("\n" if have_lines else "") + "\n".join(add) + "\n")

# --------------------------------------------------------------------------
# verify / validate / mandate
# --------------------------------------------------------------------------
def verify():
    STATE["omc"] = "skipped" if not DO["omc"] else ("ok" if omc_enabled() else "missing")
    if STATE["omc"] == "missing": FAILURES["omc"] = "OMC plugin not enabled"
    if not DO["cbm"]:
        STATE["codebase-memory-mcp"] = "skipped"
    elif have("codebase-memory-mcp") and mcp_present("codebase-memory"):
        STATE["codebase-memory-mcp"] = "ok"
    else:
        fail("codebase-memory-mcp", "missing", "binary or MCP registration missing")
    if not DO["memoryos"]:
        STATE["memoryos"] = "skipped"
    elif mcp_present("memoryos") and sorted(_memos_layers()) == ["long_term", "mid_term", "short_term"]:
        if STATE.get("memoryos") not in ("degraded",): STATE["memoryos"] = "ok"
    else:
        fail("memoryos", "missing", "MCP not registered or layers incomplete")
    if not DO["headroom"]:
        STATE["headroom"] = "skipped"
    elif headroom_importable() and plugin_listed("cc-stack-hooks"):
        STATE["headroom"] = "ok"
    else:
        fail("headroom", "degraded", "headroom import or hooks plugin missing")
    bad = [k for k in CORE if STATE.get(k) not in ("ok", "skipped")]
    for k in CORE:
        log(f"  {k:<22} {STATE.get(k, 'unknown')}")
    # integrations (optional; refresh state, never affect the overall pass/fail)
    if DO["extras"]:
        for n in ("context7", "tavily", "cloudflare-docs", "cloudflare-api"):
            if mcp_present(n):
                STATE[n] = "ok"
            elif STATE.get(n) not in ("skipped", "degraded"):
                STATE[n] = "absent"
        if plugin_listed("cloudflare") and STATE.get("cloudflare-skills") not in ("skipped",):
            STATE["cloudflare-skills"] = "ok"
        for k in EXTRA:
            log(f"  {k:<22} {STATE.get(k, 'unknown')}")
    return len(bad) == 0

def validate_claude_p():
    if not have("claude"):
        fail("core", "degraded", "claude CLI not found -> cannot run claude -p validation"); return False
    if env("CLAUDE_SESSION_ID", "") or env("CC_STACK_IN_HOOK", "") == "1":
        log("validate: inside a session/hook -> skipping nested claude -p"); return True
    log("validating via 'claude -p' (loads plugins + MCP servers)...")
    r = cap("claude", "-p", "Reply with exactly: STACK_OK", "--output-format", "stream-json",
            "--verbose", "--max-turns", "1", "--permission-mode", "bypassPermissions", timeout=180)
    if not r or r.returncode != 0 or not (r.stdout or ""):
        fail("core", "degraded", "claude -p validation could not run (auth/version? see log)")
        logf().write((r.stderr if r else "") or ""); return False
    out = (r.stdout or "").lower(); logf().write(r.stdout)
    (ok if "stack_ok" in out else warn)("validate: agent round-trip " + ("OK" if "stack_ok" in out else "no STACK_OK"))
    (ok if "oh-my-claude" in out else warn)("validate: OMC plugin " + ("loaded" if "oh-my-claude" in out else "not seen"))
    (ok if "memoryos" in out else warn)("validate: memoryos MCP " + ("loaded" if "memoryos" in out else "not seen"))
    (ok if "codebase-memory" in out else warn)("validate: codebase-memory MCP " + ("loaded" if "codebase-memory" in out else "not seen"))
    return True

def mandate():
    sym = {"ok": "OK", "degraded": "DEGRADED", "missing": "MISSING", "skipped": "skipped", "absent": "absent"}
    rows = " | ".join(f"{k}={sym.get(STATE.get(k,'?'),'?')}" for k in CORE)
    integ = " | ".join(f"{k}={sym.get(STATE.get(k,'?'),'?')}" for k in EXTRA)
    fl = "; ".join(f"{k}: {v}" for k, v in FAILURES.items())
    lines = [
        "cc-stack status: " + rows + ".",
        "Integrations: " + integ + ".",
        f"Inference backend (MemoryOS): NVIDIA NIM at {NIM_BASE_URL}; LLM {NIM_LLM_MODEL}; embeddings NIM {NIM_EMBED_MODEL}.",
        "headroom auto-compresses large tool outputs via a PostToolUse hook (reversible); MemoryOS persists decisions/profile (add_memory / retrieve_memory); query codebase-memory (search_graph/trace_call_path) before grepping; use Context7 for up-to-date library docs and Tavily for web search; delegate heavy reads to OMC subagents to keep this context lean.",
        "Validate/heal the stack before substantive work: if any CORE component is not OK, run `cc-stack heal` then `cc-stack validate`. Cloudflare API and some servers may show as absent until OAuth is completed via `/mcp`. Failure detail is in .gaintech/bootstrap.log and .gaintech/stack-state.json. Usual blockers: missing $NVIDIA_API_KEY/$TAVILY_API_KEY or container network not allowing github.com / huggingface.co / integrate.api.nvidia.com / mcp.context7.com / mcp.tavily.com / *.mcp.cloudflare.com.",
        "Treat healing as a hermeneutic circle: read each component's health against the whole, re-read the whole each session; apply the same whole<->part discipline to OMC subagent coordination.",
        "Never add AI/Claude attribution to git: no 'Co-Authored-By: Claude' trailer, no 'Generated with Claude Code' line, no Claude identity as author or co-author, in any commit or PR. Attribution is disabled by config and by a commit-msg scrubber; do not reintroduce it.",
    ]
    if fl: lines.insert(2, "Recorded failures: " + fl + ".")
    return "\n".join(lines)

# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def install_all():
    ensure_deps(); disable_attribution(); install_omc(); install_cbm(); install_memoryos(); install_hooks_plugin(); install_extra_mcps(); ensure_gitignore()
def report():
    log("================= stack summary =================")
    for k in CORE:
        log(f"  {k:<22} {STATE.get(k, 'unknown')}")
    log("  -- integrations --")
    for k in EXTRA:
        log(f"  {k:<22} {STATE.get(k, 'unknown')}")
    log(f"  {'git-attribution':<22} {STATE.get('attribution', 'unknown')}")
    for k, v in FAILURES.items():
        warn(f"  {k}: {v}")
    if not NIM_API_KEY: warn("Set NVIDIA_API_KEY in the container's Environment variables panel — MemoryOS needs it.")
    if IS_REMOTE: warn("Remote: set network = 'All' (or allow github.com, *.githubusercontent.com, huggingface.co, integrate.api.nvidia.com, registry.npmjs.org, pypi.org).")
    ok("done — `claude mcp list`, `claude plugin list`, `cc-stack status`.")

def cmd_bootstrap():
    install_all(); write_state(); validate_claude_p(); report()
def cmd_heal():
    install_all(); write_state(); report()
def cmd_doctor(hook):
    if hook:
        verify(); write_state()
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": mandate()}}))
    else:
        install_all(); verify(); write_state(); report()
def cmd_verify():
    rc = verify(); write_state(); (ok if rc else warn)("stack " + ("healthy" if rc else "degraded")); return 0 if rc else 1
def cmd_status():
    print(STATE_FILE.read_text() if STATE_FILE.exists() else '{"error":"no state yet; run cc-stack bootstrap"}')

def main():
    global MODE
    ap = argparse.ArgumentParser(prog="cc-stack", description="Claude Code stack bootstrap / self-heal")
    ap.add_argument("command", nargs="?", default="bootstrap",
                    choices=["bootstrap", "heal", "doctor", "validate", "verify", "status",
                             "hook-compress", "hook-learn", "memoryos-launch"])
    ap.add_argument("--hook", action="store_true", help="doctor: emit SessionStart additionalContext JSON")
    for c in ("omc", "cbm", "memoryos", "headroom", "extras"):
        ap.add_argument(f"--no-{c}", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    a = ap.parse_args()
    for c in ("omc", "cbm", "memoryos", "headroom", "extras"):
        if getattr(a, f"no_{c}"): DO[c] = False
    if a.reindex: os.environ["CC_REINDEX"] = "1"
    MODE = a.command
    if a.command in ("hook-compress", "hook-learn", "memoryos-launch"):
        {"hook-compress": hook_compress, "hook-learn": hook_learn, "memoryos-launch": memoryos_launch}[a.command](); return
    GAINTECH.mkdir(parents=True, exist_ok=True)
    try: open(LOG_FILE, "w").close()
    except Exception: pass
    if a.command == "bootstrap": cmd_bootstrap()
    elif a.command == "heal": cmd_heal()
    elif a.command == "doctor": cmd_doctor(a.hook)
    elif a.command == "validate": ensure_deps(); validate_claude_p()
    elif a.command == "verify": sys.exit(cmd_verify())
    elif a.command == "status": cmd_status()

if __name__ == "__main__":
    main()
