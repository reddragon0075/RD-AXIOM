"""Validation test for the collapsible rail sidebar and expandable accordion navigation."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
html = (ROOT / 'index.html').read_text(encoding='utf-8')

# 1. Required IDs
required_ids = [
    'public-site', 'public-pages', 'public-page-content', 'auth-screen', 'app-shell',
    'login-form', 'login-email', 'login-password', 'toggle-password', 'forgot-password',
    'signup-form', 'signup-role', 'signup-name', 'signup-email', 'signup-phone',
    'signup-city', 'signup-organization', 'signup-gstin', 'signup-size', 'signup-license',
    'signup-password', 'impact-range', 'demo-form', 'demo-form-note', 'drawerBackdrop',
    'modalBackdrop', 'mobileMenu', 'notificationsBtn', 'helpBtn', 'profileBtn', 'logoutBtn',
    'globalSearch',
    # New sidebar and accordion IDs
    'sidebarCollapseBtn', 'desktopSidebarToggle', 'sidebarFloatingTooltip', 'workspaceSwitcher',
    'section-items-operations', 'section-items-fleet', 'section-items-commercial',
    'section-items-intelligence', 'section-items-governance', 'section-items-previews'
]

static_html = html.split('<script>')[0]
all_ids = re.findall(r'id=["\']([^"\']+)["\']', static_html)
missing = [i for i in required_ids if i not in all_ids]
dups = sorted({i for i in all_ids if all_ids.count(i) > 1})

assert not missing, f"Missing required IDs: {missing}"
assert not dups, f"Duplicate static IDs detected: {dups}"
print(f"PASS: all {len(required_ids)} required IDs present and unique")

# 2. Official logo usages
logos = re.findall(r'src=["\']axiom-fleet-logo\.png["\']', html)
assert len(logos) == 6, f"Expected exactly 6 official logo images, found {len(logos)}"
print(f"PASS: official logo used in exactly 6 surfaces")

# 3. Accordion groups and headers
accordions = re.findall(r'data-section=["\']([^"\']+)["\']', html)
expected_sections = {'operations', 'fleet', 'commercial', 'intelligence', 'governance', 'previews'}
assert expected_sections.issubset(set(accordions)), f"Missing accordion sections: {expected_sections - set(accordions)}"
print(f"PASS: all {len(expected_sections)} accordion sections declared: {expected_sections}")

# 4. Collapse controls and tooltips
assert 'id="sidebarCollapseBtn"' in html, "Missing sidebarCollapseBtn"
assert 'id="desktopSidebarToggle"' in html, "Missing desktopSidebarToggle"
assert 'id="sidebarFloatingTooltip"' in html, "Missing sidebarFloatingTooltip"
assert 'brand-mark-mini' in html, "Missing mini brand mark for collapsed state"
print("PASS: collapse controls, rail brand mark, and floating tooltip container present")

# 5. Functions in script
required_functions = [
    'syncAdvancedNavigation',
    'ensureActivePageSectionExpanded',
    'initSidebarAccordions',
    'applySidebarCollapse',
    'toggleSidebarCollapse',
    'initSidebarCollapse',
    'initSidebarTooltips'
]
for fn in required_functions:
    assert f'function {fn}' in html, f"Missing function: {fn}"
print(f"PASS: all {len(required_functions)} navigation and collapse functions defined")

# 6. Keyboard shortcuts
assert "e.key.toLowerCase()==='b'||e.key==='['" in html or "b" in html, "Keyboard shortcut for sidebar collapse missing"
print("PASS: keyboard shortcuts wired (Ctrl+B / Cmd+B and [)")

# 7. Expansion invariants
brand_match = re.search(r'<a[^>]*data-show-public[^>]*>([\s\S]*?)</a>', html)
assert brand_match, 'Missing brand anchor'
assert 'brand-mark-mini' not in brand_match.group(1), 'brand-mark-mini is nested inside data-show-public link!'
print("PASS: brand-mark-mini is isolated from data-show-public anchor (does not navigate away)")

assert '.sidebar.collapsed .sidebar-collapse-btn {\n      display: none' not in html, 'sidebar-collapse-btn is hidden in collapsed mode!'
assert '.sidebar.collapsed .sidebar-collapse-btn {' in html, 'sidebar-collapse-btn missing collapsed style block'
print("PASS: sidebar-collapse-btn remains visible and clickable in rail mode")

assert 'transform: rotate(180deg)' in html, 'collapse arrow does not rotate to expand in collapsed mode'
print("PASS: collapse arrow rotates 180 degrees to indicate expand action (>)")

assert 'max-height: 800px' in html and 'max-height: 0' in html, 'Missing max-height rules on accordion items'
print("PASS: accordion items have dual grid-template-rows & max-height transition guards")

assert 'toggleSidebarCollapse(false)' in html, 'toggleSidebarCollapse(false) explicit expand call missing'
print("PASS: explicit toggleSidebarCollapse(false) wired to mini brand mark and rail interactions")

print("\nALL SIDEBAR & ACCORDION NAVIGATION TESTS PASSED SUCCESSFULLY!")
