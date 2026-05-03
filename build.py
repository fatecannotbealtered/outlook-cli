"""PyInstaller build script for outlook-cli.

Produces a single-file binary for each platform.
Run: python build.py
"""

import os
import platform
import subprocess
import sys
from pathlib import Path


def main():
    entry = Path("cli.py")
    if not entry.exists():
        print("Error: cli.py not found. Run from project root.")
        sys.exit(1)

    name = "outlook-cli"
    dist_dir = Path("dist")
    dist_dir.mkdir(exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", name,
        "--clean",
        "--noconfirm",
        # Explicitly collect the whole package so PyInstaller doesn't
        # miss submodules that are only imported lazily (inside functions).
        "--hidden-import", "outlook_cli",
        "--hidden-import", "outlook_cli.main",
        "--hidden-import", "outlook_cli.config",
        "--hidden-import", "outlook_cli.exchange",
        "--hidden-import", "outlook_cli.output",
        "--hidden-import", "outlook_cli.audit",
        "--hidden-import", "outlook_cli.crypto",
        "--hidden-import", "outlook_cli.commands",
        "--hidden-import", "outlook_cli.commands.mail",
        "--hidden-import", "outlook_cli.commands.cal",
        "--hidden-import", "outlook_cli.commands.folders",
        "--hidden-import", "outlook_cli.commands.rules",
        "--hidden-import", "outlook_cli.commands.tools",
        "--hidden-import", "outlook_cli.commands.setup",
        # exchangelib and its dynamic submodules
        "--hidden-import", "exchangelib",
        "--hidden-import", "exchangelib.items",
        "--hidden-import", "exchangelib.properties",
        "--hidden-import", "exchangelib.protocol",
        str(entry),
    ]

    print(f"Building {name}...")
    print(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("Build failed!")
        sys.exit(result.returncode)

    # Determine output path
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine

    ext = ".exe" if system == "windows" else ""
    binary = dist_dir / f"{name}{ext}"

    if binary.exists():
        size_mb = binary.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful!")
        print(f"  Output: {binary}")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"  Platform: {system}-{arch}")
    else:
        print(f"Warning: Expected binary not found at {binary}")


if __name__ == "__main__":
    main()
