"""FCC guard (CLI-SPEC §13): every leaf command declared by `reference` must be
invoked by at least one command-level test in tests/*.py.

The guard enforces the honesty of release_readiness.fcc_status: it runs the
full enumeration only while the tool claims "verified", so the claim cannot be
flipped without the coverage existing. A zero leaf count fails the guard
itself, so a reference schema change cannot silently disarm it.
"""

import json
from pathlib import Path

import pytest

from tests.test_e2e_cli import run_cli


def _collect_leaves(commands, out):
    for command in commands:
        children = command.get("children") or []
        if children:
            _collect_leaves(children, out)
            continue
        path = (command.get("path") or "").strip()
        if path.startswith("outlook-cli"):
            path = path[len("outlook-cli") :].strip()
        if path:
            out.append(path)


def _command_words(leaf):
    words = []
    for word in leaf.split():
        if word.startswith(("<", "[", "-")):
            break
        words.append(word)
    return words


def test_fcc_every_leaf_command_has_test():
    code, stdout, stderr = run_cli("reference", "--json")
    assert code == 0, stderr
    envelope = json.loads(stdout[stdout.find("{") :])
    assert envelope["ok"] is True

    declared = envelope["data"]["release_readiness"]["fcc_status"]
    if declared != "verified":
        pytest.skip(
            f"fcc_status is declared {declared!r}; the guard enforces enumeration only "
            'for a "verified" claim - flipping the claim without command-level tests '
            "fails the guard"
        )

    leaves = []
    _collect_leaves(envelope["data"]["commands"], leaves)
    assert leaves, "reference enumerated zero leaf commands; the FCC guard would be a no-op"

    here = Path(__file__)
    raw = "".join(
        p.read_text(encoding="utf-8") for p in here.parent.glob("test_*.py") if p.name != here.name
    )
    # Collapse whitespace so multi-line argument lists still match the needle.
    sources = " ".join(raw.split())

    missing = []
    for leaf in leaves:
        words = _command_words(leaf)
        if not words:
            continue
        covered = '"' + '", "'.join(words) + '"' in sources
        if not covered:
            missing.append(leaf)

    assert not missing, (
        f"{len(missing)}/{len(leaves)} leaf commands have no command-level test: "
        + ", ".join(sorted(missing))
    )
