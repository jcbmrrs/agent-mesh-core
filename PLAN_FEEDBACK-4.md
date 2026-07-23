# Fourth Adversarial Review of `IMPLEMENTATION_PLAN.md`

## Findings

1. **High: tokenized locks introduce crash windows that can create permanent locks.**

   The plan now writes `owner.token` after successful lock-directory `mkdir`, then returns a `LockHandle`. That prevents stale handles from deleting someone else's reacquired lock, but it creates a new failure mode: if the process crashes or token writing fails after `mkdir` but before `owner.token` is fully written, the lock directory exists forever with no valid releasable owner. Since v1 explicitly has no stale-lock breaking, this becomes a permanent manual repair case unless documented and tested.

   Recommendation: make the partial-lock states explicit. Tests should cover token-write failure after `mkdir` and assert cleanup removes the newly created lock dir. Also define operator recovery behavior for lock dirs with no `owner.token` or malformed `owner.token`, even if the answer is "manual inspect and remove only."

2. **High: `recover_processing` can race with an active scanner.**

   The plan says an empty `.processing/<claim_id>/` is simply removed because it means a crash happened right after `mkdir`, before the message rename. But an empty claim dir is also a valid transient state for a live scanner between `mkdir` and rename. If an operator runs `recover_processing` while agents are active, recovery can delete an active claim directory and cause the scanner's next rename to fail or write metadata into a missing path.

   Recommendation: apply the same age/explicit-selection rules to empty claim directories as to message-bearing claims. Document that recovery should be run while the target agent is stopped, or make the implementation resilient to its claim dir disappearing between `mkdir` and rename.

3. **High: requeue/quarantine can overwrite or collide with existing files.**

   `recover_processing(action="requeue")` moves a claimed message back to the inbox root; `action="quarantine"` moves it to `.invalid/`. The plan does not specify what happens if a file with the same original filename already exists at the destination. Message filenames are intended to be unique, but recovery is operator tooling for already-corrupt states, so collision handling needs to be explicit.

   Recommendation: fail closed on destination collision, or generate a collision-resistant recovered filename while preserving the original in metadata. Add tests for requeue and quarantine collisions so recovery never overwrites a valid message.

4. **Medium: malformed claim metadata is not covered.**

   Round 3 called out malformed sidecars, but the updated plan only covers three states: empty claim dir, message without sidecar, and message with sidecar. A sidecar can exist but be partial JSON, invalid JSON, missing `claimed_at`, or have an invalid claimant. That is likely if a process dies during sidecar write.

   Recommendation: include malformed sidecar handling in `test_inbox_recovery.py`. Treat it as recoverable/quarantinable using message mtime as the age fallback, and report the metadata parse failure clearly.

5. **Medium: lock release sequence is underspecified for non-empty directories and races.**

   With `owner.token` inside the lock directory, `release_lock` cannot just `os.rmdir(lock_dir)`; it must read the token, unlink `owner.token`, then remove the directory. The plan does not say what happens if unlink succeeds but `rmdir` fails, if `owner.token` disappears between read and unlink, or if extra unexpected files are present in the lock directory.

   Recommendation: specify the exact release sequence and failure behavior. In particular, never recursively delete unexpected contents in a lock dir. Tests should cover missing token, mismatched token, extra file present, and `rmdir` failure after token unlink.

6. **Medium: mesh-root confinement via `resolve()` needs symlink policy tests.**

   The plan confines `atomic_write_json` by resolving `target_file_path` under `mesh_root`, and `send_message` fails closed on symlink inboxes. It does not explicitly test symlinks in intermediate parent directories for generic atomic writes, such as `mesh_root/agents/foo` being a symlink outside the mesh. Depending on `Path.resolve(strict=False)` details and whether parents already exist, this can be subtle.

   Recommendation: add atomic-write tests for symlink parents and symlink target files. Since symlinks are unsupported elsewhere, fail closed for any symlink component in paths used for writes.

7. **Medium: claim directory names need their own collision/retry rule.**

   The plan says `mkdir(.processing/<claim_id>/)` "always succeeds" because the claim ID is unique. In practice, UUID/counter collisions are rare but not impossible, and a previous crashed claim can leave that directory behind. The implementation needs to decide whether `FileExistsError` retries with a new claim ID or fails the scan.

   Recommendation: require retry-on-claim-id-collision with a bounded retry count, and test `FileExistsError` on the first generated claim ID.

8. **Low/Medium: hidden-file ignore rules may hide real messages forever.**

   Inbox scan ignores hidden files and `.tmp_*`, which is sensible for temp files. But on macOS/SMB, some clients or manual operators may accidentally create dot-prefixed message files. The plan does not say whether ignored files are reported anywhere.

   Recommendation: return ignored file counts/names in `InboxScanResult` or at least log/report them in scan results. Silent ignores are hard to diagnose in a filesystem-based queue.

9. **Low: `smb_provision.py` still has a misleading console-script name.**

   The docs now say this is a dry-run command generator/validator, but `[project.scripts]` still exposes `agent-mesh-provision-smb`. A user running that command will reasonably expect it to provision SMB unless the CLI itself is very explicit.

   Recommendation: either rename the script to `agent-mesh-smb-commands` or require a `--dry-run` default with output that states no system changes were made. If an apply mode is ever added later, make it an explicit separate flag with privilege checks.

## Overall

The design has converged well. The remaining adversarial findings are mostly about partial states introduced by the safety mechanisms themselves: lock-token creation, claim-directory recovery, destination collisions, malformed sidecars, and symlink/path edge cases. These are worth tightening before implementation because they are exactly the states an SMB-backed coordination directory will accumulate after interrupted processes and manual repair attempts.
