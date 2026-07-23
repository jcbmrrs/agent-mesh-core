import re

MAX_NAME_LENGTH = 64
CLAIM_ID_RE = re.compile(r"^[0-9a-f]{32}$")
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError(f"invalid name {name!r}: expected string")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"invalid name {name!r}: too long")
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"invalid name {name!r}: expected lowercase portable path component")
    if ".." in name:
        raise ValueError(f"invalid name {name!r}: '..' is not allowed")
    if name.casefold() in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"invalid name {name!r}: reserved Windows device name")
    return name


def validate_claim_id(claim_id: str) -> str:
    if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
        raise ValueError(f"invalid claim id {claim_id!r}: expected 32 lowercase hex characters")
    return claim_id
