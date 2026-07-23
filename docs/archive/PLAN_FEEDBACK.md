# Adversarial Review of `IMPLEMENTATION_PLAN.md`

> **Archived (2026-07-23) — historical record.** Every finding here was resolved and its resolution folded into `../IMPLEMENTATION_PLAN_v2.md`'s design invariants (lock tokens, name validation, atomic claiming, etc.). Kept for the reasoning trail, not as living guidance.

## Findings

1. **High: lock staleness can break mutual exclusion.**

   `IMPLEMENTATION_PLAN.md` adds stale-lock detection/breaking to the lock cycle, but the original design only guarantees atomic `mkdir`/`rmdir`. A stale threshold based on directory mtime can delete a valid long-running lock, especially across SMB, clock skew, sleep/wake, or slow network IO. Also, `release_lock()` appears owner-blind, so an old holder could `rmdir` a lock that was broken and reacquired by another agent.

   Recommendation: either drop stale-lock breaking from v1, or define lock ownership tokens: create the lock dir, write owner/lease metadata inside it, release only if the token matches, and treat stale break as a separate explicitly tested protocol.

2. **High: agent IDs, lock names, and target IDs need path validation.**

   The API accepts `agent_id`, `target_agent_id`, and `lock_name`, and those values become paths under `agents/` and `locks/`. The plan does not require rejecting path separators, `..`, absolute paths, Windows-reserved names, or Unicode/path-normalization edge cases. Without validation, a malformed ID can escape the mesh root or collide across OSes.

   Recommendation: add a `names.py` or validator with a strict portable regex, for example `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`, and test every public method that consumes names.

3. **High: inbox scan can double-process messages.**

   The plan specifies read-and-delete behavior and tolerating concurrent delete races, but not atomic claiming. If two processes run with the same `agent_id`, both can read the same message before either deletes it. That is a realistic failure mode for restarts, watcher loops, or multiple local tools sharing one agent identity.

   Recommendation: claim first via atomic rename into a per-agent `processing/` directory or hold an inbox-scoped directory lock while scanning. Then read/delete only claimed files.

4. **Medium: `file_trees.json` contradicts the "no shared mutable file" invariant.**

   The architecture includes `config/file_trees.json` as an aggregated cluster file, but the core principle says no single shared mutable file. The implementation plan ignores this entirely.

   Recommendation: either remove `file_trees.json` from the v1 architecture or replace it with per-agent files like `agents/<id>/file_tree.json`, plus an optional read-only generated aggregate.

5. **Medium: deploy/code placement semantics are still inconsistent.**

   `PROMPT.md` asks for `/Users/Shared/AgentMesh/agent_core.py`; `PROJECT-SETUP.md` copies `src/agent_core.py` into the share; `AGENTS.md` says the live share holds runtime state only; `IMPLEMENTATION_PLAN.md` says a shim can "later" satisfy the literal path. That leaves implementers unsure whether code is ever deployed into the share.

   Recommendation: make a firm call. Preferred: no executable code in `/Users/Shared/AgentMesh`; clients install/run the package from the repo, and the live share is data-only. If a shim is required, list exactly where it lives and who consumes it.

6. **Medium: watcher support is an invariant but not in the implementation plan.**

   `AGENTS.md` says to prefer filesystem watchers over polling. The plan only builds `scan_and_clear_inbox`, with no watcher abstraction, no debounce behavior, and no guidance on SMB event reliability.

   Recommendation: either explicitly defer watchers to v2, or add a small optional watcher loop using `watchdog` behind an interface. Do not leave this as an implied production behavior.

7. **Medium: temp filenames should be globally unique, not PID-based.**

   The source boilerplate uses `.tmp_<target>_<pid>`. PIDs collide across machines, and cleanup can remove another writer's temp file if two writers hit the same target name. The plan tests message ID uniqueness, but not temp-path uniqueness.

   Recommendation: use `uuid4` or `tempfile.mkstemp(dir=target.parent, prefix=f".tmp_{target.name}.")`; then `os.replace`/`Path.replace` instead of relying on `shutil.move`.

8. **Medium: malformed inbox retention can create a permanent hot loop.**

   The plan keeps malformed JSON in place. A watcher or repeated scanner will rediscover the same bad file forever.

   Recommendation: quarantine malformed messages into `inbox/.invalid/` or rename them with a `.bad` suffix after reporting.

9. **Low/Medium: SMB provisioning is underspecified for real macOS automation.**

   The plan tests command construction, but the actual macOS permission model is the hard part: admin privileges, SMB users, share names, ACLs, current File Sharing state, Tailscale interface assumptions, and command compatibility across macOS versions.

   Recommendation: keep this as a dry-run command generator unless exact supported macOS versions, privilege expectations, rollback behavior, and manual verification steps are defined.

## Overall

The plan is strong on TDD structure, but it currently tests a few dangerous behaviors into existence: stale lock breaking, read-delete inbox scans, and unclear deployment semantics. Tighten v1 around the core invariants: strict name validation, no stale lock breaking unless tokenized, atomic message claiming, unique temp files, and a clean data-only live share.
