import importlib.util
import plistlib
from pathlib import Path

SCRIPT_PATH = Path("deploy/launchd/render_mcp_launchd_plist.py")
TEMPLATE_PATH = Path("deploy/launchd/com.jacobmorris.agent-mesh-core.mcp-server.plist.template")


def _load_render_script():
    spec = importlib.util.spec_from_file_location("render_mcp_launchd_plist", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_launchd_plist_template_supervises_mcp_server_and_writes_logs():
    plist = plistlib.loads(TEMPLATE_PATH.read_bytes())

    assert plist["Label"] == "com.jacobmorris.agent-mesh-core.mcp-server"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert plist["WorkingDirectory"] == "__REPO_DIR__"
    assert plist["EnvironmentVariables"]["UV_CACHE_DIR"] == "__REPO_DIR__/.uv-cache"
    assert plist["StandardOutPath"] == "__LOG_DIR__/mcp_server.log"
    assert plist["StandardErrorPath"] == "__LOG_DIR__/mcp_server.err.log"
    assert plist["ProgramArguments"] == [
        "__UV_BIN__",
        "run",
        "agent-mesh-mcp-server",
        "--mesh-root",
        "__MESH_ROOT__",
        "--host",
        "__TAILSCALE_HOST__",
        "--port",
        "__PORT__",
    ]


def test_render_launchd_plist_creates_log_dir_and_fills_placeholders(tmp_path):
    render_script = _load_render_script()
    output = tmp_path / "LaunchAgents" / "com.jacobmorris.agent-mesh-core.mcp-server.plist"
    log_dir = tmp_path / "logs" / "agent-mesh-core"

    render_script.render_plist(
        template_path=TEMPLATE_PATH,
        output_path=output,
        uv_bin=Path("/opt/homebrew/bin/uv"),
        repo_dir=Path("/repo/agent-mesh-core"),
        mesh_root=Path("/Users/Shared/AgentMesh"),
        tailscale_host="mac-mini.tailnet.ts.net",
        port=8000,
        log_dir=log_dir,
    )

    assert log_dir.is_dir()
    assert output.is_file()
    rendered = output.read_text(encoding="utf-8")
    assert "__" not in rendered

    plist = plistlib.loads(output.read_bytes())
    assert plist["ProgramArguments"] == [
        "/opt/homebrew/bin/uv",
        "run",
        "agent-mesh-mcp-server",
        "--mesh-root",
        "/Users/Shared/AgentMesh",
        "--host",
        "mac-mini.tailnet.ts.net",
        "--port",
        "8000",
    ]
    assert plist["WorkingDirectory"] == "/repo/agent-mesh-core"
    assert plist["EnvironmentVariables"]["UV_CACHE_DIR"] == "/repo/agent-mesh-core/.uv-cache"
    assert plist["StandardOutPath"] == str(log_dir / "mcp_server.log")
    assert plist["StandardErrorPath"] == str(log_dir / "mcp_server.err.log")
