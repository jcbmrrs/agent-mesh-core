# Multi-Agent Tailscale SMB Coordination Guide

> **Superseded — historical draft, do not implement as-is.** The Python boilerplate below (PID-based temp filenames, `shutil.move`, unvalidated `agent_id`/path components, read-then-delete inbox handling, no name validation) is the original draft this project started from. It has known correctness problems that `IMPLEMENTATION_PLAN.md` and `AGENTS.md` fix — path-safe name validation, `tempfile.mkstemp`+`os.replace` with fsync, atomic claim-before-process inbox scanning, a lock handle API, etc. Read this file for the *directory topology* and original intent only; for the actual v1 design, see `IMPLEMENTATION_PLAN.md` (build plan) and `AGENTS.md` (current invariants).

## 1. System Architecture
To avoid file-locking conflicts across macOS, Windows, and Linux, agents do not share a single monolithic state file. Instead, they communicate using an **isolated inbox topology** and **directory-based atomic operations.**

### Directory StructureCreate this structure inside your Mac mini shared folder (e.g., `/Users/Shared/AgentMesh/`):

``` text
📁 AgentMesh/
├── 📁 config/
│   ├── 📄 local_rules.json          # Read-only configuration rules for all agents
│   └── 📄 file_trees.json           # Aggregated file tree structures of the cluster
├── 📁 agents/
│   ├── 📁 agent_mac_mini/
│   │   ├── 📁 inbox/                # Other agents drop messages here
│   │   └── 📄 state.json            # Heartbeat, active tasks, local settings
│   ├── 📁 agent_mbp/
│   │   ├── 📁 inbox/
│   │   └── 📄 state.json
│   └── 📁 agent_ollama_local/
│       ├── 📁 inbox/
│       └── 📄 state.json
└── 📁 locks/                        # Used for cluster-wide atomic mutual exclusion
```

## 2. Python Boilerplate Scripts (historical, superseded — do not run)

~~Save this as `agent_core.py` on your machines.~~ Do not do this — no code is ever placed on the live share or run from this snippet. It provides robust, cross-platform file utilities that prevent data corruption and race conditions over SMB networks — that intent is real, but the implementation below is the pre-review draft with known bugs (PID-based temp names, no path validation, no lock ownership check, read-then-delete inbox handling). The corrected version is `src/agent_mesh_core/` per `IMPLEMENTATION_PLAN.md`.

```python

import os
import json
import time
import shutil
from pathlib import Path

class AgentMeshCoordinator:
    def __init__(self, mesh_root_path: str, agent_id: str):
        self.mesh_root = Path(mesh_root_path)
        self.agent_id = agent_id
        self.agent_dir = self.mesh_root / "agents" / agent_id
        self.inbox_dir = self.agent_dir / "inbox"
        self.lock_dir = self.mesh_root / "locks"
        
        # Ensure agent-specific folders exist
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def acquire_lock(self, lock_name: str, timeout: int = 10, retry_interval: float = 0.2) -> bool:
        """Acquires a global lock using atomic directory creation (cross-platform safe)."""
        lock_path = self.lock_dir / f"{lock_name}.lock"
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.mkdir(lock_path)
                return True
            except FileExistsError:
                time.sleep(retry_interval)
        return False

    def release_lock(self, lock_name: str):
        """Releases a global lock."""
        lock_path = self.lock_dir / f"{lock_name}.lock"
        try:
            os.rmdir(lock_path)
        except FileNotFoundError:
            pass

    def atomic_write_json(self, target_file_path: Path, data: dict):
        """Writes JSON data atomically via a temp file to prevent corruption over SMB."""
        target_path = Path(target_file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to a hidden temporary file in the target directory
        temp_file = target_path.parent / f".tmp_{target_path.name}_{os.getpid()}"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            # Atomic replace operation
            shutil.move(str(temp_file), str(target_path))
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise IOError(f"Atomic write failed over SMB: {e}")

    def update_state(self, status: str, tasks: list, extra_metadata: dict = None):
        """Updates this agent's global pulse and health metrics."""
        state_path = self.agent_dir / "state.json"
        payload = {
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "status": status,
            "active_tasks": tasks,
            "metadata": extra_metadata or {}
        }
        self.atomic_write_json(state_path, payload)

    def send_message(self, target_agent_id: str, message_type: str, payload: dict):
        """Drops a message payload into another agent's inbox securely."""
        target_inbox = self.mesh_root / "agents" / target_agent_id / "inbox"
        if not target_inbox.exists():
            raise FileNotFoundError(f"Target agent {target_agent_id} does not exist.")
            
        message_id = f"msg_{int(time.time() * 1000)}_{self.agent_id}.json"
        msg_file_path = target_inbox / message_id
        self.atomic_write_json(msg_file_path, {"sender": self.agent_id, "type": message_type, "body": payload})
```
