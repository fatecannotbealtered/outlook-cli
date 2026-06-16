"""setup.py for outlook-cli (development / pip install)."""

import os
import re

from setuptools import find_packages, setup


def _read_version():
    # Single source of truth: outlook_cli/__init__.py __version__ (kept in
    # lockstep with package.json by scripts/sync-version.js). Never hand-copy.
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "outlook_cli", "__init__.py"), encoding="utf-8") as f:
        match = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
    if not match:
        raise RuntimeError("Cannot find __version__ in outlook_cli/__init__.py")
    return match.group(1)


setup(
    name="outlook-cli",
    version=_read_version(),
    description="Outlook Exchange CLI for AI Agents",
    long_description=open("README.md", encoding="utf-8").read()
    if os.path.exists("README.md")
    else "",
    long_description_content_type="text/markdown",
    author="Sean Guo",
    author_email="guosong6886@gmail.com",
    url="https://github.com/fatecannotbealtered/outlook-cli",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*"]),
    data_files=[("share/outlook-cli", ["CHANGELOG.md"])],
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0,<9.0",
        "exchangelib>=4.0,<6.0",
        "cryptography>=41.0",
        "keyring>=24.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "ruff>=0.1.0",
            "pyinstaller>=6.0",
            "pip-audit>=2.7",
        ],
    },
    entry_points={
        "console_scripts": [
            "outlook-cli=outlook_cli.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Communications :: Email",
        "Topic :: Office/Business",
    ],
    keywords="outlook exchange email cli agent",
)
