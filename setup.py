"""setup.py for outlook-cli (development / pip install)."""

from setuptools import setup, find_packages

setup(
    name="outlook-cli",
    version="1.0.0",
    description="Outlook Exchange CLI for humans and AI Agents",
    long_description=open("README.md", encoding="utf-8").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Sean Guo",
    author_email="guosong6886@gmail.com",
    url="https://github.com/fatecannotbealtered/outlook-cli",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0,<9.0",
        "exchangelib>=4.0,<6.0",
        "cryptography>=41.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "ruff>=0.1.0",
            "pyinstaller>=6.0",
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
