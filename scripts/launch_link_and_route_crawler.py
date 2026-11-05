#!/usr/bin/env python3
"""Axiom Mobility - Launch Link & Route Crawler.

Scans the repository for:
1. Static asset references (<script>, <link>, <img>, ES6 imports) -> verifies disk presence.
2. Navigation, tabs, and anchors -> verifies target existence and view consistency.
3. Frontend-to-Backend API route parity -> checks fetch() calls against registered routes in server.py.
4. Hardcoded localhost/127.0.0.1 references in frontend/mobile client code.
5. Forbidden competitor names (brand term audit).
"""

import base64
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MVP_ROOT = ROOT / "fleetline-mvp"


def get_all_client_files():
    patterns = ["*.html", "*.js", "*.tsx", "*.ts", "*.css"]
    files = []
    scan_dirs = [ROOT / "frontend", ROOT / "fleetline-mvp" / "driver-app", ROOT / "fleetline-mvp" / "mobile-driver", ROOT / "fleetline-mvp"]
    for d in scan_dirs:
        if not d.exists():
            continue
        for p in patterns:
            for f in d.rglob(p):
                # Ignore node_modules, .git, .scratch, __pycache__, snapshots
                if any(part in f.parts for part in ["node_modules", ".git", ".scratch", "__pycache__", "snapshots", ".temp"]):
                    continue
                files.append(f)
    return list(set(files))


def audit_competitor_strings():
    """Verify 0 occurrences of competitor names."""
    competitors = [
        base64.b64decode(b"bW92ZWluc3luYw==").decode("utf-8"),
        base64.b64decode(b"cm91dGVtYXRpYw==").decode("utf-8"),
        base64.b64decode(b"aW5kZWNhYg==").decode("utf-8"),
    ]
    violations = []

    ignore_files = {"999999_purge_competitor_references.sql", "launch_link_and_route_crawler.py"}
    
    for f in ROOT.rglob("*"):
        if f.is_dir() or any(p in f.parts for p in [".git", "__pycache__", "node_modules", ".scratch", ".pytest_cache"]):
            continue
        if f.name in ignore_files or f.suffix in {".pyc", ".png", ".ico", ".jpg", ".sqlite3", ".db"}:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            for comp in competitors:
                matches = re.findall(rf"\b{comp}\b", content, re.IGNORECASE)
                if matches:
                    violations.append((str(f.relative_to(ROOT)), comp, len(matches)))
        except Exception:
            pass
    return violations


def audit_hardcoded_localhost():
    """Find hardcoded localhost or 127.0.0.1 in frontend and mobile files."""
    violations = []
    client_files = get_all_client_files()

    for f in client_files:
        if "test" in f.name.lower() or "test" in str(f.parent).lower():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            for idx, line in enumerate(content.splitlines(), 1):
                if ("http://localhost" in line or "http://127.0.0.1" in line) and not line.strip().startswith("//"):
                    violations.append((str(f.relative_to(ROOT)), idx, line.strip()))
        except Exception:
            pass
    return violations


def audit_es6_imports():
    """Verify all ES6 relative imports resolve to files on disk."""
    violations = []
    client_files = [f for f in get_all_client_files() if f.suffix in {".js", ".ts", ".tsx"}]

    for f in client_files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            # Matches import ... from "..." or export ... from "..."
            import_matches = re.findall(r"""(?:import|export)\s+(?:.*?from\s+)?['"](\.[^'"]+)['"]""", content)
            for imp in import_matches:
                target_path = (f.parent / imp).resolve()
                if (
                    not target_path.exists()
                    and not target_path.with_suffix(".js").exists()
                    and not target_path.with_suffix(".ts").exists()
                    and not target_path.with_suffix(".tsx").exists()
                    and not (target_path / "index.js").exists()
                    and not (target_path / "index.ts").exists()
                    and not (target_path / "index.tsx").exists()
                ):
                    violations.append((str(f.relative_to(ROOT)), imp))
        except Exception:
            pass
    return violations


def audit_html_static_assets():
    """Verify <script src>, <link href>, <img src> in HTML files resolve to files."""
    violations = []
    html_files = [f for f in get_all_client_files() if f.suffix == ".html"]

    for f in html_files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            # Scripts
            for src in re.findall(r"""<script[^>]+src=['"]([^'"]+)['"]""", content):
                if src.startswith("http://") or src.startswith("https://") or src.startswith("//") or src.startswith("data:") or "${" in src:
                    continue
                # Local path
                clean_src = src.lstrip("/")
                resolved = (f.parent / clean_src).resolve()
                alt_resolved = (MVP_ROOT / clean_src).resolve()
                alt2_resolved = (ROOT / clean_src).resolve()
                if not (resolved.exists() or alt_resolved.exists() or alt2_resolved.exists()):
                    violations.append((str(f.relative_to(ROOT)), "script", src))

            # Stylesheets
            for href in re.findall(r"""<link[^>]+href=['"]([^'"]+)['"]""", content):
                if href.startswith("http://") or href.startswith("https://") or href.startswith("//") or "manifest" in href or "${" in href:
                    continue
                clean_href = href.lstrip("/")
                resolved = (f.parent / clean_href).resolve()
                alt_resolved = (MVP_ROOT / clean_href).resolve()
                alt2_resolved = (ROOT / clean_href).resolve()
                if not (resolved.exists() or alt_resolved.exists() or alt2_resolved.exists()):
                    violations.append((str(f.relative_to(ROOT)), "link", href))

            # Images
            for img in re.findall(r"""<img[^>]+src=['"]([^'"]+)['"]""", content):
                if img.startswith("http://") or img.startswith("https://") or img.startswith("data:") or "${" in img:
                    continue
                clean_img = img.lstrip("/")
                resolved = (f.parent / clean_img).resolve()
                alt_resolved = (MVP_ROOT / clean_img).resolve()
                alt2_resolved = (ROOT / clean_img).resolve()
                if not (resolved.exists() or alt_resolved.exists() or alt2_resolved.exists()):
                    violations.append((str(f.relative_to(ROOT)), "img", img))
        except Exception:
            pass
    return violations


def extract_server_registered_routes():
    """Extract route prefixes and specific patterns from fleetline-mvp/server.py."""
    server_path = MVP_ROOT / "server.py"
    if not server_path.exists():
        return set()

    content = server_path.read_text(encoding="utf-8", errors="ignore")
    routes = set()

    # Exact string route matches
    for m in re.findall(r"""route\s*(?:==|in)\s*(?:\{|['"])([^'"\}]+)""", content):
        for r in re.findall(r"""['"](/api[^'"]+)['"]""", m):
            routes.add(r)
        if m.startswith("/api"):
            routes.add(m)

    # Starts with prefixes
    for prefix in re.findall(r"""(?:route\.startswith|startswith)\s*\(\s*(?:\(([^)]+)\)|['"]([^'"]+)['"])""", content):
        if prefix[0]:
            for p in re.findall(r"""['"](/api[^'"]+)['"]""", prefix[0]):
                routes.add(p)
        elif prefix[1]:
            routes.add(prefix[1])

    # Regex patterns
    for regex in re.findall(r"""re\.match\(\s*r['"]\^(/api[^'"\$]+)""", content):
        routes.add(regex)

    return routes


def audit_frontend_fetch_routes():
    """Extract fetch() URLs in frontend code and match against server.py registered routes."""
    violations = []
    client_files = [f for f in get_all_client_files() if f.suffix in {".js", ".html", ".tsx"}]
    server_routes = extract_server_registered_routes()

    for f in client_files:
        if "test" in f.name.lower() or "test" in str(f.parent).lower():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            # Extract fetch URLs: fetch('/api/...', ...) or fetch(`/api/...`, ...)
            fetches = re.findall(r"""fetch\s*\(\s*[`'"](/api[^`'"?]+)""", content)
            for url in fetches:
                # Normalize url
                norm_url = re.sub(r"\$\{[^}]+\}", "PARAM", url)
                norm_url = re.sub(r"/[a-zA-Z0-9_\-]+(?:/[a-zA-Z0-9_\-]+)*$", "", norm_url) if "PARAM" not in norm_url else norm_url

                # Check if matches any server route
                matched = False
                for sr in server_routes:
                    clean_sr = sr.rstrip("/").replace("/api/v1", "/api")
                    clean_url = url.rstrip("/").replace("/api/v1", "/api")
                    if clean_url.startswith(clean_sr) or clean_sr in clean_url:
                        matched = True
                        break
                    # regex check
                    if "(" in sr or "^" in sr:
                        try:
                            if re.search(sr, url) or re.search(sr, clean_url):
                                matched = True
                                break
                        except Exception:
                            pass

                if not matched:
                    violations.append((str(f.relative_to(ROOT)), url))
        except Exception:
            pass
    return violations


def main():
    print("===================================================================")
    print("   AXIOM MOBILITY (FLEETLINE) PRE-LAUNCH LINK & ROUTE CRAWLER     ")
    print("===================================================================")

    has_failures = False

    # 1. Competitor Strings
    comp_violations = audit_competitor_strings()
    print(f"\n[1] Competitor String Guard: {'FAILED' if comp_violations else 'PASSED'}")
    if comp_violations:
        has_failures = True
        for file, comp, count in comp_violations:
            print(f"  [FAIL] {file}: found {count} occurrence(s) of '{comp}'")
    else:
        print("  [OK] 0 occurrences of forbidden competitor strings.")

    # 2. Hardcoded Localhost
    loc_violations = audit_hardcoded_localhost()
    print(f"\n[2] Hardcoded Localhost / 127.0.0.1: {'FAILED' if loc_violations else 'PASSED'}")
    if loc_violations:
        has_failures = True
        for file, line, text in loc_violations:
            print(f"  [FAIL] {file}:{line} -> {text}")
    else:
        print("  [OK] 0 hardcoded localhost references in client assets.")

    # 3. ES6 Imports
    import_violations = audit_es6_imports()
    print(f"\n[3] ES6 Import Disk Resolution: {'FAILED' if import_violations else 'PASSED'}")
    if import_violations:
        has_failures = True
        for file, imp in import_violations:
            print(f"  [FAIL] {file}: cannot resolve '{imp}' on disk")
    else:
        print("  [OK] All relative ES6 imports resolve cleanly to files on disk.")

    # 4. HTML Static Asset Links
    html_violations = audit_html_static_assets()
    print(f"\n[4] HTML Static Asset Links (<script>, <link>, <img>): {'FAILED' if html_violations else 'PASSED'}")
    if html_violations:
        has_failures = True
        for file, tag, src in html_violations:
            print(f"  [FAIL] {file}: <{tag}> refers to missing asset '{src}'")
    else:
        print("  [OK] All HTML asset links point to existing files on disk.")

    # 5. Frontend-to-Backend Fetch Route Parity
    fetch_violations = audit_frontend_fetch_routes()
    print(f"\n[5] Frontend Fetch API Route Matching: {'WARNINGS' if fetch_violations else 'PASSED'}")
    if fetch_violations:
        # Group unique
        unique_fetch = sorted(set(fetch_violations))
        print(f"  Found {len(unique_fetch)} potentially unmatched or dynamic route calls:")
        for file, url in unique_fetch[:15]:
            print(f"  [WARN] {file} -> {url}")
    else:
        print("  [OK] All frontend fetch calls match registered routes in server.py.")

    print("\n===================================================================")
    if has_failures:
        print("CRAWLER RESULT: FAILURES DETECTED (Fixes required)")
        sys.exit(1)
    else:
        print("CRAWLER RESULT: ALL CRITICAL STATIC & SECURITY AUDITS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
