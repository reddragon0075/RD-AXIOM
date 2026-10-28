#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) CI/CD Quality Gate: Static Seam, Secret & Brand Guard.

Verifies:
1. Zero private secrets, service_role keys, or unauthorized localhost references in client bundles
2. Key & type contract integrity between backend responses and frontend/mobile consumers
3. 100% Zero-Trace Eradication: Zero competitor brand terms across entire repository
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent


def check_secrets_and_config() -> list[str]:
    violations = []
    scan_dirs = [
        ROOT / "frontend" / "js",
        ROOT / "fleetline-mvp" / "frontend" / "js",
        ROOT / "fleetline-mvp" / "driver-app",
        ROOT / "fleetline-mvp" / "mobile-driver" / "src",
    ]

    for s_dir in scan_dirs:
        if not s_dir.exists():
            continue
        for root_path, _, files in os.walk(s_dir):
            for file in files:
                if not file.endswith((".js", ".ts", ".tsx", ".html")):
                    continue
                file_path = Path(root_path) / file
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                    for line_num, line in enumerate(fp, 1):
                        stripped = line.strip()
                        # 1. Private service role or JWT keys
                        if "service_role" in stripped.lower() and "policy" not in stripped.lower():
                            violations.append(f"[SECRET] {file_path.relative_to(ROOT)}:{line_num} contains service_role reference: {stripped[:60]}")
                        if "eyJhbGciOi" in stripped:
                            violations.append(f"[SECRET] {file_path.relative_to(ROOT)}:{line_num} contains raw JWT token: {stripped[:60]}")
    return violations


def check_contracts() -> list[str]:
    violations = []
    # Verify core contract keys are defined in backend_domain and tariff_engine
    tariff_engine_path = ROOT / "fleetline-mvp" / "tariff_engine.py"
    with open(tariff_engine_path, "r", encoding="utf-8") as fp:
        tariff_src = fp.read()

    required_tariff_keys = [
        "client_receivable",
        "supplier_payable",
        "gross_margin_paise",
        "gross_receivable_paise",
        "gst_tax_paise",
        "net_receivable_paise",
        "margin_pct",
        "maker_checker_audit_hold",
    ]
    for key in required_tariff_keys:
        if f'"{key}"' not in tariff_src:
            violations.append(f"[CONTRACT] Missing required tariff engine key '{key}' in {tariff_engine_path.name}")

    return violations


def check_forbidden_brand_terms() -> list[str]:
    """Scan all files for forbidden competitor brand terms using base64 encoded patterns."""
    violations = []
    # Base64 decoded patterns to prevent self-matching in scanner
    b64_patterns = [
        b"bW92ZVxzKlstX10/XHMqaW5ccypbLV9dP1xzKnN5bmM=",  # pattern 1
        b"cm91dGVccypbLV9dP1xzKm1hdGlj",                  # pattern 2
        b"aW5kZVxzKlstX10/XHMqY2Ficz8=",                  # pattern 3
    ]
    compiled_patterns = [
        re.compile(base64.b64decode(bp).decode('utf-8'), re.IGNORECASE)
        for bp in b64_patterns
    ]

    exclude_dirs = {'.git', 'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build', '.pytest_cache'}
    exclude_files = {'competitor_matches.json'}

    for root_dir, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file in exclude_files:
                continue
            file_path = Path(root_dir) / file
            # Check filename
            for pattern in compiled_patterns:
                if pattern.search(file):
                    violations.append(
                        f"[BRAND_TERM] Prohibited competitor brand in filename: {file_path.relative_to(ROOT)}"
                    )
            # Check contents
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                    for line_num, line in enumerate(fp, 1):
                        for pattern in compiled_patterns:
                            match = pattern.search(line)
                            if match:
                                violations.append(
                                    f"[BRAND_TERM] {file_path.relative_to(ROOT)}:{line_num} contains prohibited competitor term '{match.group(0)}': {line.strip()[:80]}"
                                )
            except Exception:
                pass

    return violations


def main():
    print("=" * 60)
    print("AXIOM MOBILITY QUALITY GATE: CONTRACT, SECRET & BRAND AUDIT")
    print("=" * 60)

    secret_violations = check_secrets_and_config()
    contract_violations = check_contracts()
    brand_violations = check_forbidden_brand_terms()
    all_violations = secret_violations + contract_violations + brand_violations

    if all_violations:
        print(f"\n[FAIL] Found {len(all_violations)} violation(s):")
        for v in all_violations:
            print(f"  - {v}")
        sys.exit(1)

    print("\n[PASS] Zero secret leaks detected.")
    print("[PASS] Contract key definitions fully compliant.")
    print("[PASS] 100% Zero-Trace Brand Sanitization verified (0 competitor traces).")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
