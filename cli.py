"""PyInstaller entry point.

This file exists so PyInstaller sees a top-level script that imports
the outlook_cli package via absolute imports, preserving the package
structure.  Source installs use `outlook_cli.main:main` directly (via
setup.py console_scripts); only the binary build uses this file.
"""

from outlook_cli.main import main

if __name__ == "__main__":
    main()
