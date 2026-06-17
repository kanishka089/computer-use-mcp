"""Installer for computer-use-mcp.

Creates .venv/, installs the package + deps, copies .env.example to .env, and
registers the server in Claude Desktop's config (with a backup). Also prints the
Claude Code (`claude mcp add`) form.

Run with Python 3.10 or 3.11:   py -3.10 install.py
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
VENV_DIR = ROOT / ".venv"
SERVER_MODULE = "realhands.server"
SERVER_NAME = "computer-use"


def _venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _claude_desktop_config() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Claude" / "claude_desktop_config.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def step(msg: str) -> None:
    print(f"\n>> {msg}")


def _register_claude_desktop(py: Path) -> None:
    cfg_path = _claude_desktop_config()
    entry = {"command": py.as_posix(), "args": ["-m", SERVER_MODULE]}

    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            print(f"    Could not parse {cfg_path}; leaving it untouched.")
            print("    Add this manually under \"mcpServers\":")
            print(f'      "{SERVER_NAME}": {json.dumps(entry)}')
            return
        backup = cfg_path.with_suffix(".json.bak")
        shutil.copyfile(cfg_path, backup)
        print(f"    Backed up existing config to {backup}")
    else:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    servers = data.setdefault("mcpServers", {})
    servers[SERVER_NAME] = entry
    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"    Registered '{SERVER_NAME}' in {cfg_path}")
    print("    Restart Claude Desktop, then look for the 'computer-use' tool.")


def main() -> int:
    if sys.version_info < (3, 10):
        print(f"ERROR: Python 3.10+ required (you have {sys.version.split()[0]}).")
        return 1
    if sys.version_info >= (3, 13):
        print(f"WARNING: Python {sys.version.split()[0]} is newer than tested (3.10/3.11).")

    step("Creating virtualenv at .venv/")
    if VENV_DIR.exists():
        print("    .venv already exists, reusing.")
    else:
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])

    py = _venv_python()
    if not py.exists():
        print(f"ERROR: expected venv Python at {py} but it's not there.")
        return 1

    step("Upgrading pip in the venv")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    step("Installing computer-use-mcp + dependencies")
    subprocess.check_call([str(py), "-m", "pip", "install", "-e", str(ROOT), "--quiet"])

    step("Setting up .env")
    env_file = ROOT / ".env"
    if env_file.exists():
        print("    .env already exists, leaving untouched.")
    else:
        shutil.copyfile(ROOT / ".env.example", env_file)
        print(f"    Created {env_file} (defaults are fine for a normal setup).")

    step("Registering with Claude Desktop")
    _register_claude_desktop(py)

    step("Claude Code (optional)")
    print("    To also use it from Claude Code, run:")
    print(f'      claude mcp add {SERVER_NAME} -- "{py.as_posix()}" -m {SERVER_MODULE}')

    print("\nDone. Panic hotkey = ctrl+alt+q. Mouse to top-left corner also aborts.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
