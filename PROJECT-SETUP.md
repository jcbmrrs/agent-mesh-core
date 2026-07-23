# Agent Mesh Core Project Set-up

> **Superseded — historical draft, do not implement as-is.** The `deploy.sh` below (flat `cp` of `src/agent_core.py`, bash `[ -f ... ]` existence check for `local_rules.json`) and the repo layout it assumes are both superseded. Real source is the `src/agent_mesh_core/` uv package (not a flat script); the overwrite guard lives in tested Python (`rules_template.write_local_rules_template`'s `force` flag), not bash; and `deploy.sh`'s actual, narrower job is defined in `IMPLEMENTATION_PLAN.md`'s "Resolved after second adversarial review" section. Read this file for the *why* (clean context windows, revertible logic, git-clone-per-machine) — the mechanics are in `IMPLEMENTATION_PLAN.md`.

## The Recommended Architecture
Keep your project split cleanly into two distinct zones:

```text

📁 YOUR_REPOSITORIES/agent-mesh-core/  <-- THIS IS YOUR GIT REPO
├── .gitignore                         # Ignores local testing outputs
├── README.md
├── deploy.sh                          # One-click script to copy code to the share
├── PROMPT.md                          # Saved here for future agents to read
└── src/
    ├── agent_core.py                  # Your boilerplate script
    └── templates/                     # Master templates for rules
        └── local_rules.template.json

---

📁 /Users/Shared/AgentMesh/            <-- THIS IS YOUR ACTIVE DATA SHARE
├── 📁 config/                         # Populated via deploy.sh or by agents
│   └── local_rules.json               
├── 📁 agents/                         # Live runtime folders (NEVER IN GIT)
│   ├── 📁 agent_mac_mini/
│   └── 📁 agent_mbp/
└── 📁 locks/

```

## Step 1: Create Your `.gitignore`
In the root of your Git repository, make sure your `.gitignore` prevents any runtime data or local node states from accidentally leaking into your source control:

```text

# Ignore live runtime files if you do a local test run
.tmp_*
*.lock
agents/
locks/
config/*.json
!config/*.template.json

# OS specific overrides
.DS_Store
Thumbs.db

```

## Step 2: Create a `deploy.sh` Script (historical, superseded — do not run as written)

~~Save this as `deploy.sh` in your Git repo~~ — the actual `deploy.sh` per `IMPLEMENTATION_PLAN.md` does not `cp` any code (`agent_core.py` doesn't exist; the real package is `src/agent_mesh_core/`, installed on each machine via its own `git pull`/`uv sync`) and does not reimplement the "don't overwrite" check in bash. Read below for the original *intent* only.

```bash

#!/bin/bash

# Target deployment directory
TARGET_DIR="/Users/Shared/AgentMesh"

echo "🚀 Deploying Agent Mesh Core to $TARGET_DIR..."

# 1. Create target directories if they don't exist
mkdir -p "$TARGET_DIR/config"
mkdir -p "$TARGET_DIR/locks"
mkdir -p "$TARGET_DIR/agents"

# 2. Copy the Python core utility
cp src/agent_core.py "$TARGET_DIR/"

# 3. Only deploy base rules if they don't already exist (prevents overwriting live config)
if [ ! -f "$TARGET_DIR/config/local_rules.json" ]; then
    echo "📄 Creating initial local_rules.json from template..."
    cp src/templates/local_rules.template.json "$TARGET_DIR/config/local_rules.json"
fi

echo "✅ Deployment complete! Shared folder updated cleanly."

```

## Why this approach is better for Claude Code & Codex
1. **Clean Context Windows:** When you point Claude Code or Codex at a clean Git repo, it won't get bogged down reading hundreds of megabytes of old agent logs, file-tree traces, or active heartbeats. It only sees your actual code logic.
2. **Version Control for Logic, Not State:** If an agent makes a mistake in `agent_core.py` and breaks the lock mechanics, you can instantly run `git` rollback. If your live data folder were tracked, rolling back would wipe out genuine agent messages and state updates.
3. **Multi-Machine Sync:** When you eventually spin up that Linux box or Windows gaming rig, you can simply run `git clone` on those machines to get the code, point them to the mounted SMB share path, and they are instantly ready to coordinate.