"""Project version information."""

from __future__ import annotations

import re

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

__version__ = "0.1.1"

if not VERSION_PATTERN.fullmatch(__version__):
    raise RuntimeError("MeshBridge version must use major.minor.subminor format")
