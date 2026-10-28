"""Permanent CI Quality Gate: 100% Zero-Trace Brand Sanitization Assertion.

Ensures that competitor brand terms (and case variants) can never be introduced
into any file across the repository.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def test_zero_trace_brand_sanitization():
    """Assert zero competitor brand terms exist across all repository files."""
    b64_patterns = [
        b"bW92ZVxzKlstX10/XHMqaW5ccypbLV9dP1xzKnN5bmM=",  # pattern 1
        b"cm91dGVccypbLV9dP1xzKm1hdGlj",                  # pattern 2
        b"aW5kZVxzKlstX10/XHMqY2Ficz8=",                  # pattern 3
    ]
    compiled_patterns = [
        re.compile(base64.b64decode(bp).decode("utf-8"), re.IGNORECASE)
        for bp in b64_patterns
    ]

    exclude_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".pytest_cache"}
    exclude_files = {".git", "competitor_matches.json"}

    violations = []

    for root_dir, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file in exclude_files:
                continue
            file_path = Path(root_dir) / file
            # Check filename
            for pattern in compiled_patterns:
                if pattern.search(file):
                    violations.append(f"Filename violation: {file_path.relative_to(ROOT)}")
            # Check content
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                    for line_num, line in enumerate(fp, 1):
                        for pattern in compiled_patterns:
                            match = pattern.search(line)
                            if match:
                                violations.append(
                                    f"{file_path.relative_to(ROOT)}:{line_num} -> '{match.group(0)}' in: {line.strip()[:60]}"
                                )
            except Exception:
                pass

    assert len(violations) == 0, f"Found {len(violations)} competitor brand term violations:\n" + "\n".join(violations)
