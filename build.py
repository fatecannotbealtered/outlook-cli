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
    entry = Path("outlook_cli/main.py")
    if not entry.exists():
        print("Error: outlook_cli/main.py not found. Run from project root.")
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
