# Role & Goal
You are an expert systems automation engineer setting up a multi-agent file-mesh infrastructure on this host Mac mini. The objective is to establish an always-on, zero-port-forwarding, Tailscale SMB-accessible data directory structured for agent communication (Claude Code, Codex, Ollama cluster) via text, settings, and JSON file primitives.

# System Context
- Host: Always-on Mac mini (macOS) accessible externally via Tailscale.
- Network Target: Clients (MBP M3 Pro, plus upcoming Linux and Windows rigs) will mount this share via its Tailscale IP.
- Expected Messaging Style: Isolated inbox directories, JSON structures, rules sharing, and distributed file trees.

# Tasks to Execute
Please execute the following steps sequentially directly on this system:

1. **Verify or Propose Folder Location**:
   - Check if `/Users/Shared/AgentMesh` exists. If not, create it.
   
2. **Generate the Mesh Directory Architecture**:
   - Programmatically build out the following empty folder hierarchy inside the root folder:
     - `config/`
     - `locks/`
     - `agents/agent_mac_mini/inbox/`
     - `agents/agent_mbp/inbox/`
     - `agents/agent_ollama_local/inbox/`

3. **Deploy Core Coordination Scripts**:
   - Create a Python file named `/Users/Shared/AgentMesh/agent_core.py` containing an `AgentMeshCoordinator` class that handles:
     - Atomic directory-based locks (`os.mkdir` / `os.rmdir`) to prevent race conditions over cross-platform SMB mounts.
     - Atomic JSON operations using local hidden temporary files shifted seamlessly via `shutil.move` to prevent packet-drop JSON corruptions over Tailscale links.
     - An inbox scanning function that processes messages and deletes them out of the agent's inbox folder upon reading.

4. **Populate Initial Base Rules**:
   - Create a base configuration file at `config/local_rules.json`. Include boilerplate configuration metadata detailing global network context, active model overrides for Claude/Ollama, and exclusion guidelines for file tree indexes.

5. **Provide the System Automation Strategy**:
   - Write a short utility script or outline the specific macOS native CLI commands (`sharing` utility, `dscl` commands, or UI guidance) to cleanly export this directory via SMB, ensuring proper Read/Write access flags are pinned for Tailscale connected nodes.

Verify your creations by checking directory structures and mocking an atomic write test script to ensure operations run without warnings.

