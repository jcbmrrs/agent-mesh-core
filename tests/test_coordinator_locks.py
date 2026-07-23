from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_mesh_core.coordinator import AgentMeshCoordinator
from conftest import FakeClock


def test_acquire_lock_writes_owner_token(coordinator_factory, mesh_root):
    coordinator = coordinator_factory("agent_a")

    handle = coordinator.acquire_lock("shared")

    assert handle
    assert handle.lock_name == "shared"
    assert handle.token
    assert (mesh_root / "locks" / "shared" / "owner.token").read_text() == handle.token


def test_acquire_lock_timeout_without_real_sleep(mesh_root):
    clock = FakeClock()
    first = AgentMeshCoordinator(mesh_root, "agent_a", clock=clock)
    second = AgentMeshCoordinator(mesh_root, "agent_b", clock=clock)
    assert first.acquire_lock("shared")

    assert second.acquire_lock("shared", timeout=0.2, retry_interval=0.1) is None
    assert clock.sleeps == [0.1, 0.1]


def test_release_matching_token_removes_lock(coordinator_factory, mesh_root):
    coordinator = coordinator_factory("agent_a")
    handle = coordinator.acquire_lock("shared")

    coordinator.release_lock(handle)

    assert not (mesh_root / "locks" / "shared").exists()
    coordinator.release_lock(handle)


def test_release_missing_or_mismatched_token_is_noop(coordinator_factory, mesh_root):
    coordinator = coordinator_factory("agent_a")
    handle = coordinator.acquire_lock("shared")
    token_file = mesh_root / "locks" / "shared" / "owner.token"
    token_file.write_text("different")

    coordinator.release_lock(handle)

    assert token_file.read_text() == "different"
    token_file.unlink()
    coordinator.release_lock(handle)
    assert (mesh_root / "locks" / "shared").is_dir()


def test_release_raises_when_extra_files_keep_lock_dir_non_empty(coordinator_factory, mesh_root):
    coordinator = coordinator_factory("agent_a")
    handle = coordinator.acquire_lock("shared")
    (mesh_root / "locks" / "shared" / "extra").write_text("x")

    with pytest.raises(OSError):
        coordinator.release_lock(handle)

    assert (mesh_root / "locks" / "shared" / "extra").exists()


def test_token_write_failure_rolls_back_and_retries(monkeypatch, mesh_root):
    clock = FakeClock()
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a", clock=clock)
    calls = 0
    original = coordinator._write_lock_token

    def flaky(path, token):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("boom")
        original(path, token)

    monkeypatch.setattr(coordinator, "_write_lock_token", flaky)

    handle = coordinator.acquire_lock("shared", timeout=0.1, retry_interval=0.1)

    assert handle
    assert calls == 2
    assert (mesh_root / "locks" / "shared" / "owner.token").exists()


def test_two_coordinator_contention_then_success(mesh_root):
    clock = FakeClock()
    first = AgentMeshCoordinator(mesh_root, "agent_a", clock=clock)
    second = AgentMeshCoordinator(mesh_root, "agent_b", clock=clock)
    handle = first.acquire_lock("shared")
    assert second.acquire_lock("shared", timeout=0, retry_interval=0) is None

    first.release_lock(handle)

    assert second.acquire_lock("shared", timeout=0, retry_interval=0)


def test_thread_pool_exactly_one_winner(mesh_root):
    coordinators = [AgentMeshCoordinator(mesh_root, f"agent_{i}") for i in range(8)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        handles = list(pool.map(lambda c: c.acquire_lock("shared"), coordinators))

    assert sum(handle is not None for handle in handles) == 1


def test_lock_name_validated_before_mkdir(monkeypatch, coordinator_factory):
    coordinator = coordinator_factory("agent_a")

    def fail_mkdir(_path):
        raise AssertionError("mkdir should not be called")

    monkeypatch.setattr("agent_mesh_core.coordinator.os.mkdir", fail_mkdir)
    with pytest.raises(ValueError):
        coordinator.acquire_lock("../bad")
