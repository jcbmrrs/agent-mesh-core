import pytest

from agent_mesh_core import bootstrap
from agent_mesh_core.bootstrap import bootstrap_mesh


def test_bootstrap_mesh_creates_dirs_and_rules(mesh_root):
    bootstrap_mesh(mesh_root, ["agent_mac_mini", "agent_mbp"])

    assert (mesh_root / "agents" / "agent_mac_mini" / "inbox").is_dir()
    assert (mesh_root / "agents" / "agent_mbp" / "inbox").is_dir()
    assert (mesh_root / "locks").is_dir()
    assert (mesh_root / "config" / "local_rules.json").is_file()


def test_bootstrap_rejects_duplicate_after_normalization_before_creating_anything(mesh_root):
    with pytest.raises(ValueError):
        bootstrap_mesh(mesh_root, ["agent_mbp", "Agent_MBP"])

    assert not mesh_root.exists()


def test_bootstrap_surfaces_rules_refuse_to_overwrite(mesh_root):
    bootstrap_mesh(mesh_root, ["agent_mac_mini"])

    with pytest.raises(FileExistsError):
        bootstrap_mesh(mesh_root, ["agent_mac_mini"])


def test_bootstrap_force_rules_overwrites(mesh_root):
    bootstrap_mesh(mesh_root, ["agent_mac_mini"])

    bootstrap_mesh(
        mesh_root,
        ["agent_mac_mini"],
        rules_overrides={"network_context": {"transport": "forced"}},
        force_rules=True,
    )


def test_bootstrap_call_order_dirs_before_rules(monkeypatch, mesh_root):
    seen = {}
    original = bootstrap.write_local_rules_template

    def spy(mesh_root_arg, **kwargs):
        seen["dir_exists"] = (mesh_root / "agents" / "agent_a" / "inbox").is_dir()
        return original(mesh_root_arg, **kwargs)

    monkeypatch.setattr(bootstrap, "write_local_rules_template", spy)

    bootstrap_mesh(mesh_root, ["agent_a"])

    assert seen["dir_exists"] is True


def test_bootstrap_main_maps_agent_ids(mesh_root):
    assert bootstrap.main(["--mesh-root", str(mesh_root), "--agent-ids", "agent_a,agent_b"]) == 0
    assert (mesh_root / "agents" / "agent_a" / "inbox").is_dir()
    assert (mesh_root / "agents" / "agent_b" / "inbox").is_dir()
