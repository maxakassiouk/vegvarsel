"""Shared test helpers."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

if sys.platform == "win32":
    # Local development on Windows only (CI runs on Linux): asyncio's event
    # loop there opens a TCP socket pair to itself, which Home Assistant's
    # test plugin blocks. HTTP is mocked in the tests either way.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def route_points() -> list[tuple[float, float]]:
    data = json.loads((FIXTURES / "route_aalesund_vigra.json").read_text(encoding="utf-8"))
    return [tuple(p) for p in data["points"]]


@pytest.fixture
def situations_xml() -> bytes:
    return load_fixture("situations_synthetic.xml")
