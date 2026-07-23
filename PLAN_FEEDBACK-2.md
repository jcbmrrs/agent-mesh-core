# Second Adversarial Review of `IMPLEMENTATION_PLAN.md`

## Findings

1. **High: atomic inbox claiming creates a new stuck-message failure mode.**

   The update fixes double-processing by renaming inbox files into `inbox/.processing/` before reading. That is the right direction, but the plan does not define what happens if a process crashes, is killed, loses the SMB mount, or raises after the claim but before delete/quarantine. The message will be invisible to future scans because the plan also says scans ignore anything already in `.processing/`.

   Recommendation: define a recovery policy for claimed-but-unfinished messages. At minimum, document a manual repair command and add tests for crash leftovers being reported. Better: claim into `.processing/<claim_id>/message.json` with claimant/timestamp metadata, and provide a conservative `recover_processing()` utility that requeues or quarantines old claims only when explicitly invoked.

2. **High: source docs still contain unsafe superseded boilerplate.**

   `IMPLEMENTATION_PLAN.md` and `AGENTS.md` now say no executable code goes into `/Users/Shared/AgentMesh`, no PID-based temp files, and no read-then-delete inbox scanning. But `MULTI-AGENT-GUIDE.md` still tells readers to save `agent_core.py` on machines and includes the original unsafe boilerplate: PID-based temp files, `shutil.move`, unvalidated path components, and read/delete semantics omitted from the class. `PROJECT-SETUP.md` still shows `deploy.sh` copying `src/agent_core.py` into the live share and doing the config existence check in bash. `PROMPT.md` still asks for `/Users/Shared/AgentMesh/agent_core.py`.

   Recommendation: either update those documents to match the new v1 architecture or add prominent "historical/superseded" warnings above the stale snippets. Otherwise a future agent can follow the wrong file and implement exactly the behavior the plan rejected.

3. **High: `deploy.sh` responsibility is internally inconsistent.**

   The plan says `deploy.sh` "only ever writes data" and never copies code into the live share, but also says it "confirms the target machine's checkout is up to date" and invokes `uv run agent-mesh-bootstrap`. Those are materially different deployment models: one script that mutates the live data share, versus one script that updates code on each participating machine.

   Recommendation: split this into two commands or make the boundary explicit. For example: `bootstrap-share.sh` writes only `/Users/Shared/AgentMesh` data on the Mac mini, while each client manually runs `git pull && uv sync` in its own checkout. If `deploy.sh` performs `git pull`, say where it runs, which checkout it mutates, and whether network access/merge conflicts are allowed.

4. **Medium: lock release remains owner-blind.**

   Dropping stale-lock breaking removes the worst mtime hazard, but `release_lock(lock_name)` still removes the lock directory solely by name. If code accidentally calls release twice, or two coordinator instances use the same `agent_id`, or a caller releases a lock it failed to acquire, the API cannot detect misuse once the directory exists.

   Recommendation: v1 can keep simple directory locks, but the plan should explicitly test and document ownership limitations. A safer v1 API would return a small lock handle from `acquire_lock()` and require that handle for release, even if the handle only records process-local ownership.

5. **Medium: atomic write durability is underspecified.**

   The plan now uses `tempfile.mkstemp` and `os.replace`, which fixes name collisions. It does not say to close the `mkstemp` file descriptor, flush the Python file object, or `fsync` before replacement. On network filesystems, the atomic rename property protects readers from partial destination files, but it does not guarantee the renamed data reached durable storage if the client or mount fails at a bad moment.

   Recommendation: specify the exact write sequence: `mkstemp` in the target directory, write JSON, flush, `os.fsync(fd)`, close, `os.replace`, then best-effort cleanup. Add tests that the descriptor is closed and temp cleanup does not unlink another writer's file.

6. **Medium: message ordering is still underspecified.**

   Inbox processing is sorted by filename, while send-message uniqueness may use a monotonic counter or UUID suffix under identical timestamps. Across machines, clocks can move backward or differ by seconds, so filename ordering is not a reliable causal or wall-clock order. If ordering matters for tasks, this design will occasionally surprise callers.

   Recommendation: declare ordering semantics explicitly: either "best-effort filename order only, no cross-sender causal ordering" or add a per-sender sequence number in the payload. Tests should assert the documented behavior, not imply stronger ordering than the system can provide.

7. **Medium: `local_rules.json` single-writer language conflicts with bootstrap behavior.**

   `AGENTS.md` says `config/local_rules.json` is written only by the human operator, while `IMPLEMENTATION_PLAN.md` has `bootstrap_mesh` and `deploy.sh` writing it. That is fine if bootstrap is a human-invoked administrative action, but the distinction matters because the package will expose a console script any agent process could run.

   Recommendation: define "operator/admin tooling" versus "agent runtime API." Consider separating runtime coordinator functions from bootstrap/config-writing commands and documenting that normal agents must not call bootstrap against a live share.

8. **Low/Medium: name validation does not mention Windows reserved device names or case collisions.**

   The added validation rejects separators, dots, whitespace, and non-ASCII, but the plan does not mention Windows-reserved names like `CON`, `PRN`, `AUX`, `NUL`, `COM1`, or `LPT1`, nor case-insensitive collisions such as `agent_mbp` versus `Agent_MBP` on macOS/Windows mounts.

   Recommendation: require lowercase-only names and reject Windows device names. Also test that bootstrap rejects duplicate agent IDs after normalization.

9. **Low: SMB provisioning remains half in scope.**

   The plan says "full PROMPT.md scope" includes a macOS SMB provisioning script, but later says the module is a dry-run command generator only and real provisioning is manual follow-up. That is a reasonable v1 scope, but the document should stop calling it full provisioning.

   Recommendation: rename the module/scope to `smb_provision_plan.py` or `smb_commands.py`, or explicitly state that v1 emits/validates commands but does not safely apply system configuration.

## Overall

The updated plan resolves the first review's most serious design mistakes, especially stale-lock breaking, path validation, PID temp names, and read-then-delete inbox scans. The remaining risk is mostly coherence and recovery: stale docs still describe the rejected design, claimed messages can disappear into `.processing/`, and deployment/provisioning boundaries are still easy to misread. Tighten those before implementation so the test suite does not encode another set of ambiguous operational assumptions.
