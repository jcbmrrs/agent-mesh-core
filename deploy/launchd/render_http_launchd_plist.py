#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).with_name(
    "com.jacobmorris.agent-mesh-core.http-server.plist.template"
)
DEFAULT_OUTPUT = (
    Path.home() / "Library" / "LaunchAgents" / "com.jacobmorris.agent-mesh-core.http-server.plist"
)
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "agent-mesh-core"


def render_plist(
    *,
    template_path: Path,
    output_path: Path,
    uv_bin: Path,
    repo_dir: Path,
    mesh_root: Path,
    tailscale_host: str,
    port: int,
    log_dir: Path,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rendered = template_path.read_text(encoding="utf-8")
    replacements = {
        "__UV_BIN__": str(uv_bin),
        "__REPO_DIR__": str(repo_dir),
        "__MESH_ROOT__": str(mesh_root),
        "__TAILSCALE_HOST__": tailscale_host,
        "__PORT__": str(port),
        "__LOG_DIR__": str(log_dir),
    }
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)

    leftovers = [placeholder for placeholder in replacements if placeholder in rendered]
    if leftovers:
        raise ValueError(f"unrendered launchd placeholders remain: {', '.join(leftovers)}")

    output_path.write_text(rendered, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="render_http_launchd_plist.py")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--uv-bin", type=Path, required=True)
    parser.add_argument("--repo-dir", type=Path, required=True)
    parser.add_argument("--mesh-root", type=Path, default=Path("/Users/Shared/AgentMesh"))
    parser.add_argument("--tailscale-host", required=True)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args(argv)

    output = render_plist(
        template_path=args.template,
        output_path=args.output,
        uv_bin=args.uv_bin,
        repo_dir=args.repo_dir,
        mesh_root=args.mesh_root,
        tailscale_host=args.tailscale_host,
        port=args.port,
        log_dir=args.log_dir,
    )
    print(f"wrote {output}")
    print(f"created log directory {args.log_dir}")
    print(f"load with: launchctl bootstrap gui/$(id -u) {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
