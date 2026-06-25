"""Contract conformance tests (CLI-SPEC §6 / fleet governance).

Assert that every E_* code in EXIT_CODE_BY_ERROR is registered in
contract_gen.CODES with the exact exit code and retryability, that
RETRYABLE_ERRORS matches the contract, that SCHEMA_VERSION matches, and that
the success/error envelopes carry only the canonical top-level keys.
"""

from outlook_cli import contract_gen, output

# Every E_* code this tool can emit.  Keep in sync with EXIT_CODE_BY_ERROR.
ALL_ERROR_CODES = list(output.EXIT_CODE_BY_ERROR.keys())

# Independent hardcoded expected table — de-tautologizes the contract-delegating
# assertions so a wrong contract.json would still be caught here.
# E_USAGE/E_VALIDATION=2; E_NOT_FOUND=3; E_AUTH/E_FORBIDDEN/E_CONFIG=4;
# E_CONFIRMATION_REQUIRED=5; E_CONFLICT=6; E_NETWORK/E_RATE_LIMITED/E_SERVER=7 (retryable);
# E_TIMEOUT=8 (retryable); E_INTEGRITY/E_IO/E_UNKNOWN=1;
# E_INTERRUPTED=130 (retryable); non-retryable otherwise.
_EXPECTED = {
    "E_USAGE":                 {"exit": 2,   "retryable": False},
    "E_VALIDATION":            {"exit": 2,   "retryable": False},
    "E_NOT_FOUND":             {"exit": 3,   "retryable": False},
    "E_AUTH":                  {"exit": 4,   "retryable": False},
    "E_FORBIDDEN":             {"exit": 4,   "retryable": False},
    "E_CONFIG":                {"exit": 4,   "retryable": False},
    "E_CONFIRMATION_REQUIRED": {"exit": 5,   "retryable": False},
    "E_CONFLICT":              {"exit": 6,   "retryable": False},
    "E_NETWORK":               {"exit": 7,   "retryable": True},
    "E_RATE_LIMITED":          {"exit": 7,   "retryable": True},
    "E_SERVER":                {"exit": 7,   "retryable": True},
    "E_TIMEOUT":               {"exit": 8,   "retryable": True},
    "E_INTEGRITY":             {"exit": 1,   "retryable": False},
    "E_IO":                    {"exit": 1,   "retryable": False},
    "E_UNKNOWN":               {"exit": 1,   "retryable": False},
    "E_INTERRUPTED":           {"exit": 130, "retryable": True},
}


def test_error_codes_in_contract():
    """Every emitted E_* code must be in contract_gen.CODES with exact exit."""
    # Also cover codes in contract_gen.CODES that are not in EXIT_CODE_BY_ERROR
    all_codes = set(ALL_ERROR_CODES) | set(contract_gen.CODES.keys())
    for code in sorted(all_codes):
        assert code in contract_gen.CODES, (
            f"{code!r} is not in contract_gen.CODES (core∪ext)"
        )
        spec = contract_gen.CODES[code]
        tool_exit = output.exit_code_for(code)
        assert tool_exit == spec["exit"], (
            f"exit drift for {code!r}: tool={tool_exit} contract={spec['exit']}"
        )


def test_retryable_matches_contract():
    """RETRYABLE_ERRORS must match contract_gen.retryable for every emitted code."""
    for code in ALL_ERROR_CODES:
        if code not in contract_gen.CODES:
            continue
        contract_retryable = contract_gen.retryable(code)
        tool_retryable = code in output.RETRYABLE_ERRORS
        assert tool_retryable == contract_retryable, (
            f"retryable drift for {code!r}: tool={tool_retryable} contract={contract_retryable}"
        )


def test_independent_exit_retryable_table():
    """Independent hardcoded table catches wrong contract.json drift."""
    for code, expected in _EXPECTED.items():
        actual_exit = output.exit_code_for(code)
        actual_retryable = contract_gen.retryable(code)
        assert actual_exit == expected["exit"], (
            f"exit mismatch for {code!r}: got={actual_exit} expected={expected['exit']}"
        )
        want_retryable = expected["retryable"]
        assert actual_retryable == want_retryable, (
            f"retryable mismatch for {code!r}: got={actual_retryable} want={want_retryable}"
        )


def test_schema_version_matches():
    assert output.SCHEMA_VERSION == contract_gen.SCHEMA_VERSION, (
        f"schema_version drift: output={output.SCHEMA_VERSION!r} "
        f"contract={contract_gen.SCHEMA_VERSION!r}"
    )


def _envelope_keys(env: dict) -> set[str]:
    return set(env.keys())


def test_success_envelope_keys():
    env = output.success_envelope({"x": 1})
    canonical = set(contract_gen.SUCCESS_ENVELOPE_KEYS)
    extra = _envelope_keys(env) - canonical
    assert not extra, f"success envelope has unexpected keys: {extra}"
    for req in ("ok", "schema_version", "meta", "data"):
        assert req in env, f"success envelope missing required key {req!r}"


def test_error_envelope_keys():
    env = output.error_envelope("test", "E_VALIDATION")
    canonical = set(contract_gen.ERROR_ENVELOPE_KEYS)
    extra = _envelope_keys(env) - canonical - {"error"}
    assert not extra, f"error envelope has unexpected keys: {extra}"
    for req in ("ok", "schema_version", "meta"):
        assert req in env, f"error envelope missing required key {req!r}"


def test_meta_keys():
    allowed = set(contract_gen.META_REQUIRED_KEYS) | set(contract_gen.META_OPTIONAL_KEYS)
    for builder, label in (
        (lambda: output.success_envelope({"x": 1}), "success"),
        (lambda: output.error_envelope("m", "E_VALIDATION"), "error"),
    ):
        env = builder()
        meta = env.get("meta", {})
        extra = set(meta.keys()) - allowed
        assert not extra, f"{label} meta has unexpected keys: {extra}"
        for req in contract_gen.META_REQUIRED_KEYS:
            assert req in meta, f"{label} meta missing required key {req!r}"
