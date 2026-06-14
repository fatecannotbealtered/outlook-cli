"""Schema guard: every leaf command declared by `reference` must expose a real,
non-stub output_schema and at least one runnable example.

This is the honesty counterpart to the FCC guard: the old hardcoded stub
(`{"type": "object", "additionalProperties": true}`) carried zero shape
information, so an agent could not know a command's payload before calling it.
The guard fails if any leaf reverts to a stub, points at a missing/empty
schema label, or ships without an example.
"""

import json

from tests.test_e2e_cli import run_cli


def _collect_leaves(commands, out):
    for command in commands:
        children = command.get("children") or []
        if children:
            _collect_leaves(children, out)
            continue
        if (command.get("path") or "").strip():
            out.append(command)


def test_every_leaf_command_has_real_schema_and_example():
    code, stdout, stderr = run_cli("reference", "--json")
    assert code == 0, stderr
    data = json.loads(stdout[stdout.find("{") :])["data"]

    schemas = data.get("schemas") or {}
    assert schemas, "reference exposed no top-level `schemas` table"

    leaves = []
    _collect_leaves(data["commands"], leaves)
    assert leaves, "reference enumerated zero leaf commands; the guard would be a no-op"

    bad_schema = []
    no_example = []
    for cmd in leaves:
        path = cmd["path"]
        label = cmd.get("output_schema")
        # A stub (the old dict form) or a label missing from `schemas`, or one
        # whose definition has no fields, all count as no real schema.
        if not isinstance(label, str) or label not in schemas:
            bad_schema.append(path)
        elif not schemas[label].get("fields"):
            bad_schema.append(path)
        if not cmd.get("examples"):
            no_example.append(path)

    assert not bad_schema, "leaf commands without a real output_schema: " + ", ".join(
        sorted(bad_schema)
    )
    assert not no_example, "leaf commands without an example: " + ", ".join(sorted(no_example))


def test_schema_labels_have_valid_shape():
    code, stdout, _ = run_cli("reference", "--json")
    assert code == 0
    schemas = json.loads(stdout[stdout.find("{") :])["data"]["schemas"]
    for label, schema in schemas.items():
        assert schema.get("shape") in {"object", "array"}, f"{label} has invalid shape"
        assert schema.get("fields"), f"{label} has empty fields"
