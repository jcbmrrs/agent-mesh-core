import re

import pytest

from agent_mesh_core.names import validate_claim_id, validate_name


@pytest.mark.parametrize("name", ["agent_mac_mini", "agent-mbp-2", "a", "agent.mbp"])
def test_validate_name_accepts_typical_ids(name):
    assert validate_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "agent/mac",
        r"agent\mac",
        "..",
        "agent..mac",
        "/agent",
        ".agent",
        "-agent",
        "a" * 65,
        "agent mac",
        "agent_é",
        "Agent_MBP",
        "con",
        "prn",
        "aux",
        "nul",
        "com1",
        "com9",
        "lpt1",
        "lpt9",
        "CON",
    ],
)
def test_validate_name_rejects_unsafe_values(name):
    with pytest.raises(ValueError, match=re.escape(repr(name))):
        validate_name(name)


def test_validate_name_does_not_sanitize_or_lowercase():
    with pytest.raises(ValueError):
        validate_name("Agent")


def test_validate_claim_id_accepts_generated_format():
    claim_id = "0123456789abcdef0123456789abcdef"
    assert validate_claim_id(claim_id) == claim_id


@pytest.mark.parametrize(
    "claim_id",
    [
        "",
        "0123456789abcdef0123456789abcde",
        "0123456789abcdef0123456789abcdef0",
        "0123456789ABCDEF0123456789abcdef",
        "g123456789abcdef0123456789abcdef",
        "0123456789abcdef/123456789abcde",
        "..",
    ],
)
def test_validate_claim_id_rejects_anything_but_generated_format(claim_id):
    with pytest.raises(ValueError, match=re.escape(repr(claim_id))):
        validate_claim_id(claim_id)
