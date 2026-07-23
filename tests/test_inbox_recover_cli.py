import pytest

from agent_mesh_core import inbox


def test_recover_main_maps_arguments(monkeypatch, capsys):
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return [{"ok": True}]

    monkeypatch.setattr(inbox, "recover_processing", spy)

    rc = inbox.recover_main(
        [
            "--mesh-root",
            "/tmp/mesh",
            "--agent-id",
            "agent_a",
            "--older-than-seconds",
            "10",
            "--claim-id",
            "0" * 32,
            "--claim-id",
            "1" * 32,
            "--action",
            "requeue",
        ]
    )

    assert rc == 0
    assert seen == {
        "mesh_root": "/tmp/mesh",
        "agent_id": "agent_a",
        "older_than_seconds": 10.0,
        "claim_ids": ["0" * 32, "1" * 32],
        "action": "requeue",
    }
    assert '"ok":true' in capsys.readouterr().out


def test_recover_main_dry_run_forces_report(monkeypatch):
    seen = {}
    monkeypatch.setattr(inbox, "recover_processing", lambda **kwargs: seen.update(kwargs) or [])

    inbox.recover_main(
        ["--mesh-root", "/tmp/mesh", "--agent-id", "agent_a", "--action", "quarantine", "--dry-run"]
    )

    assert seen["action"] is None


def test_recover_main_missing_required_args_exits_cleanly():
    with pytest.raises(SystemExit):
        inbox.recover_main(["--mesh-root", "/tmp/mesh"])
