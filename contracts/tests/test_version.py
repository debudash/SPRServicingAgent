import re

from contracts import CONTRACTS_VERSION


def test_contracts_version_is_semver() -> None:
    # Every contract change bumps this version,
    # so lanes can tell which interface they built against.
    assert re.fullmatch(r"\d+\.\d+\.\d+", CONTRACTS_VERSION)
