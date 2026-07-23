# AgentMesh Background Information

> **Archived — historical Q&A, superseded by the MCP-server pivot decision (2026-07-23).** This doc's SMB-mount-by-every-client model (mount_smbfs, cifs-utils, `net use`, SMB provisioning) no longer applies: only the Mac mini ever touches the mesh root now, reached by other machines through a local MCP server (Ollama tooling via an HTTP wrapper) over Tailscale. See `../PROBLEM_STATEMENT.md` and `../../AGENTS.md`'s "Architecture decision" section for the current design. Kept for the original problem-framing Q&A, which is still accurate.

Q: Can I use a Mac shared folder as a communication path for multiple agents and computers?
A: Yes, you can use a Mac shared folder as an indirect memory and communication path for multiple agents and computers. However, because agents (like LLM-based assistants) lack native file-locking awareness by default, this approach requires structured setups to prevent race conditions and file overwrites.

Q: What type of data the agents are sharing (JSON payloads, text files, media, or logs)?
A: primarily JSON and text for coordination of activities between agents, communicating between machines to share info like settings, local rules, file trees, etc. Hosted on desktop Mac mini always on and connected, accessible via Tailscale everywhere without ports blocked (not on work machine)

Q: How many computers/agents will be connecting to this folder? Are the agent computers all Macs, or a mix of Windows/Linux?
A: right now, Mac mini as host and personal MBP M3 Pro as secondary. May include another older Mac for some processing, and may also include a new linux installation or Windows on an old gaming rig that is sitting off and idle. primarily Macs, but may include Linux and Windows in the future.

Q: What agents will be using this?
A: Agents are Claude Code and Codex, plus some local Ollama installations on each machine. May expand in the future.

Q: Do you want a boilerplate script for atomic JSON file updates or a cross-platform mounting script?
A: Yes, help create a markdown guide for implementing this concept, plus the boilerplate scripts, and a PROMPT.md with something I can give to Claude Code or Codex to full implement on my Mac mini (See: `MULTI-AGENT-GUIDE.md` and `PROMPT.md`).

Q: should these files or the scripts be in a git repo or should I store the "make" files someplace else and just deploy to this folder?
A: You should absolutely keep your scripts, templates, schema definitions, and infrastructure configuration in a **Git repository**, but you should not track the live execution directory (AgentMesh/) where the agents are actively writing state and text files. Tracking live agent data files in Git causes constant merge conflicts, corrupts history with millions of rapidly updating files, and spikes disk usage unnecessarily.

## How to Set It Up

- [x] **Enable SMB Sharing**: On the host Mac, go to `System Settings > General > Sharing`, turn on `File Sharing`, and click the info button.
- [x] **Configure Folder & Permissions**: Select the folder you want to use (e.g., in /Users/Shared), control-click, and adjust permissions so all required agent computers have *Read & Write* access
- [ ] **Connect from Agents**: On the other computers or agent nodes, use `Finder > Go > Connect to Server` and mount the drive using the host Mac's network path (e.g., `smb://Mac-IP-Address/SharedName`)

## Best Practices for Multi-Agent Communication
- **Use a Coordinator Pattern**: To prevent data collisions where multiple agents try to write to the same file simultaneously, designate one agent to handle all file operations while others query that agent via API or queue tasks.
- **File Naming Conventions**: Give each agent a specific, isolated file to write to (e.g., `agent_alpha_responses.txt`), rather than sharing a single global document.
- **Polling Mechanics**: Have your agents watch the shared directory for changes using a file system watcher, such as `launchd` triggers on macOS, to immediately notify an agent when a peer leaves a message or output file in the shared directory

Using a centralized Mac mini shared folder via Tailscale SMB is a highly effective, low-overhead way to coordinate multi-agent environments across different operating systems.

## Shared Directory Architecture
To keep agents from overwriting each other's data, use an **append-only ledger** or an **isolated inbox/outbox mailbox topology** rather than a single shared global JSON file.

```text

📁 Mac_Mini_Shared_Folder/
├── 📁 global_config/
│   ├── 📄 local_rules.json          <-- Read-only for agents; written only by you
│   └── 📄 network_topology.json
├── 📁 agents/
│   ├── 📁 agent_mac_mini/
│   │   ├── 📁 inbox/                <-- Other agents drop messages here
│   │   └── 📄 state.json            <-- Heartbeat, current task, file tree
│   ├── 📁 agent_mbp/
│   │   ├── 📁 inbox/
│   │   └── 📄 state.json
│   └── 📁 agent_linux/
│       ├── 📁 inbox/
│       └── 📄 state.json
└── 📁 locks/                        <-- Directory-based token bucket for mutual exclusion

```

## OS-Specific Connection Guide (Tailscale SMB)

Since your Mac mini is always on and connected via Tailscale, ensure you use the **Tailscale MagicDNS name** or the stable **100.x.y.z Tailscale IP** to mount the drives. This completely bypasses local router port blocking.

### 1. **Host Setup (Mac mini)**
- [x] Go to `System Settings > General > Sharing > File Sharing`.
- [x] Click the **(i)** icon, add your coordination folder, and grant **Read & Write** permissions to your user account.
- [x] Click **Options...** and ensure **"Share files and folders using SMB"** is checked.

### 2. **Client macOS Setup (MBP M3 Pro & Older Mac)**
- [ ] In Finder, press `Cmd + K`.
- [ ] Enter: `smb://100.x.y.z/SharedFolderName` (replace with your Mac mini's Tailscale IP).
- [ ] To automate this for background agents, use a startup bash script or a Python subprocess call to mount it via CLI:

```bash

mount_smbfs //username:password@100.x.y.z/SharedFolderName /Volumes/AgentShare

```
### 3. Client Linux Setup (Future Linux Instance)
Linux handles SMB via the `cifs-utils` package. Use the `_netdev` flag so systemd waits for the Tailscale network interface to wrap up before attempting the mount:

```bash

sudo apt-get install cifs-utils
sudo mkdir /mnt/agentshare
sudo mount -t cifs -o username=mac_user,password=mac_pass,uid=1000,gid=1000,_netdev //100.x.y.z/SharedFolderName /mnt/agentshare

```

### 4. Client Windows Setup

Windows natively supports SMB natively over Tailscale without modifications:
- [ ] Open Command Prompt or a Python script and map it to a persistent drive letter:

```cmd

net use Z: \\100.x.y.z\SharedFolderName /user:mac_user mac_pass /persistent:yes

```

## Critical Technical Protections for Agents
Because SMB handles cross-platform file locking inconsistently (Mac AFP tags vs. Linux POSIX vs. Windows Opportunistic Locking), your Python or Node.js agent scripts must handle data safety at the **application layer**.
- **Atomic Writes via Temp Files:** Never write directly to a shared JSON file. If an agent loses connection mid-write, the JSON corrupts. Have the agent write to a local temporary file first, then use an atomic move/rename operation to replace the destination file.
- **Directory-Based Lockouts:** If two agents must access a single global resource, use directory creation as a locking mechanism. Creating a directory (`os.mkdir()`) is an atomic operation across all target operating systems. If `mkdir` succeeds, the agent holds the lock; if it throws an error, the agent must wait.
- **Polling Avoidance (Use Watchers)**: Instead of constant hard-drive polling loops that spike CPU usage on the Mac mini, use cross-platform file system events (like the `watchdog` library in Python) to trigger agent actions only when a file modified event actually fires.

## Open Questions
1. Should we integrate a file watcher loop inside the Python script to read messages instantly?
2. Do you want an automated system to auto-generate the index of your file trees?