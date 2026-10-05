import subprocess
import time
import urllib.request
import json
import os
import shutil
import base64
import asyncio
import websockets

ARTIFACTS_DIR = os.environ.get("AXIOM_ARTIFACTS_DIR", r"C:\Users\91782\.gemini\antigravity-ide\brain\447ca603-dddf-4ce4-9547-460571294134")
PROFILE_DIR = os.path.abspath("temp_chrome_profile")

async def send_cmd(ws, method, params=None, msg_id_holder=[0]):
    msg_id_holder[0] += 1
    msg_id = msg_id_holder[0]
    payload = {"id": msg_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(payload))
    while True:
        resp_raw = await ws.recv()
        resp = json.loads(resp_raw)
        if resp.get("id") == msg_id:
            if "error" in resp:
                raise RuntimeError(f"CDP error: {resp['error']}")
            return resp.get("result", {})

async def eval_js(ws, expr):
    res = await send_cmd(ws, "Runtime.evaluate", {
        "expression": expr,
        "returnByValue": True,
        "awaitPromise": True
    })
    if "exceptionDetails" in res:
        raise RuntimeError(f"JS Exception: {res['exceptionDetails']}")
    return res.get("result", {}).get("value")

async def take_screenshot(ws, filename):
    res = await send_cmd(ws, "Page.captureScreenshot", {"format": "png"})
    data = base64.b64decode(res["data"])
    out_path = os.path.join(ARTIFACTS_DIR, filename)
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"Captured screenshot: {filename} ({len(data)} bytes)")
    return out_path

async def run_tests():
    if os.path.exists(PROFILE_DIR):
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    port = 9224

    proc = subprocess.Popen([
        chrome_path,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={PROFILE_DIR}",
        "--window-size=1440,900",
        "--disable-gpu",
        "--no-first-run",
        "http://127.0.0.1:4173/#login"
    ])

    try:
        # Wait for Chrome to start CDP
        for _ in range(25):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as resp:
                    tabs = json.loads(resp.read().decode())
                    if tabs:
                        break
            except Exception:
                time.sleep(0.4)
        else:
            raise RuntimeError("Failed to connect to Chrome CDP endpoint")

        tab = next((t for t in tabs if "127.0.0.1:4173" in t.get("url", "")), tabs[0])
        ws_url = tab["webSocketDebuggerUrl"]
        print("Connected to Chrome via CDP:", ws_url)

        async with websockets.connect(ws_url) as ws:
            await send_cmd(ws, "Page.enable")
            await send_cmd(ws, "Runtime.enable")
            await send_cmd(ws, "DOM.enable")

            # Route requests to local Python backend by disabling Supabase adapter in this test session
            await send_cmd(ws, "Page.addScriptToEvaluateOnNewDocument", {
                "source": "window.AXIOM_SUPABASE_CONFIG = { enabled: false };"
            })

            print("Navigating to http://127.0.0.1:4173/#login...")
            await send_cmd(ws, "Page.navigate", {"url": "http://127.0.0.1:4173/#login"})

            # Wait for login form to appear
            for _ in range(20):
                has_form = await eval_js(ws, "Boolean(document.getElementById('login-form') && document.getElementById('login-email'))")
                if has_form:
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("login-form did not load")

            print("Disabling Supabase adapter in runtime...")
            await eval_js(ws, "if (window.AxiomSupabaseAdapter) window.AxiomSupabaseAdapter.enabled = false;")

            print("Logging in via apiRequest('/api/auth/login')...")
            auth_result = await eval_js(ws, """
                (async () => {
                    try {
                        if (window.AxiomSupabaseAdapter) window.AxiomSupabaseAdapter.enabled = false;
                        const res = await apiRequest('/api/auth/login', {
                            method: 'POST',
                            body: JSON.stringify({ email: 'admin@blueorbit.in', password: 'motion2026' })
                        });
                        await showApp();
                        return { ok: true, user: currentUser?.email };
                    } catch (e) {
                        return { ok: false, error: e.message };
                    }
                })()
            """)
            print("Auth result:", auth_result)
            assert auth_result["ok"], f"Login failed: {auth_result}"

            # Wait for hydration and app-shell to become visible
            for _ in range(30):
                shell_visible = await eval_js(ws, """
                    (() => {
                        const shell = document.getElementById('app-shell');
                        const sidebar = document.getElementById('sidebar');
                        return Boolean(shell && shell.classList.contains('is-visible') && sidebar && sidebar.getBoundingClientRect().width > 200);
                    })()
                """)
                if shell_visible:
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("App shell did not become visible and sized > 200 after login")

            print("App shell loaded and visible with full sidebar!")
            time.sleep(1)

            # ---------------------------------------------------------
            # TEST 1: Check initial expanded sidebar state
            # ---------------------------------------------------------
            init_metrics = await eval_js(ws, """
                (() => {
                    const sidebar = document.getElementById('sidebar');
                    const rect = sidebar.getBoundingClientRect();
                    const collapseBtn = document.getElementById('sidebarCollapseBtn');
                    const brandMini = document.getElementById('sidebarBrandMini');
                    return {
                        width: rect.width,
                        isCollapsed: sidebar.classList.contains('collapsed'),
                        collapseBtnDisplay: window.getComputedStyle(collapseBtn).display,
                        collapseBtnTitle: collapseBtn.title,
                        brandMiniDisplay: window.getComputedStyle(brandMini).display
                    };
                })()
            """)
            print("\n[TEST 1] Initial Expanded State:", init_metrics)
            assert init_metrics["width"] > 200, f"Expected width > 200, got {init_metrics['width']}"
            assert not init_metrics["isCollapsed"], "Sidebar should not have .collapsed"
            assert init_metrics["collapseBtnDisplay"] != "none", "Collapse button should be visible"
            assert "Collapse" in init_metrics["collapseBtnTitle"], "Title should say Collapse"
            assert init_metrics["brandMiniDisplay"] == "none", "Mini brand mark should be hidden in expanded state"
            print("PASS: Test 1 - Expanded sidebar initial state verified.")

            # ---------------------------------------------------------
            # TEST 2: COLLAPSE sidebar using #sidebarCollapseBtn
            # ---------------------------------------------------------
            print("\n[TEST 2] Clicking #sidebarCollapseBtn to COLLAPSE...")
            await eval_js(ws, "document.getElementById('sidebarCollapseBtn').click()")
            time.sleep(0.5)

            collapsed_metrics = await eval_js(ws, """
                (() => {
                    const sidebar = document.getElementById('sidebar');
                    const collapseBtn = document.getElementById('sidebarCollapseBtn');
                    const brandMini = document.getElementById('sidebarBrandMini');
                    const rect = sidebar.getBoundingClientRect();
                    return {
                        width: rect.width,
                        isCollapsed: sidebar.classList.contains('collapsed'),
                        collapseBtnDisplay: window.getComputedStyle(collapseBtn).display,
                        collapseBtnTitle: collapseBtn.title,
                        brandMiniDisplay: window.getComputedStyle(brandMini).display,
                        brandMiniTitle: brandMini.title,
                        appShellClass: document.getElementById('app-shell').className
                    };
                })()
            """)
            print("[TEST 2] Collapsed Rail State:", collapsed_metrics)
            assert collapsed_metrics["width"] < 100, f"Expected width < 100, got {collapsed_metrics['width']}"
            assert collapsed_metrics["isCollapsed"], "Sidebar should have .collapsed class"
            assert collapsed_metrics["collapseBtnDisplay"] != "none", "Collapse button MUST NOT be hidden in rail mode!"
            assert "Expand" in collapsed_metrics["collapseBtnTitle"], f"Expected 'Expand' in title, got: {collapsed_metrics['collapseBtnTitle']}"
            assert collapsed_metrics["brandMiniDisplay"] != "none", "Mini brand mark MUST be visible in rail mode!"
            print("PASS: Test 2 - Sidebar collapsed into rail mode; expand button is prominently visible with 'Expand' title.")

            await take_screenshot(ws, "01_sidebar_collapsed_rail.png")

            # ---------------------------------------------------------
            # TEST 3: EXPAND sidebar using #sidebarCollapseBtn
            # ---------------------------------------------------------
            print("\n[TEST 3] Clicking #sidebarCollapseBtn to EXPAND...")
            await eval_js(ws, "document.getElementById('sidebarCollapseBtn').click()")
            time.sleep(0.5)

            expanded_metrics = await eval_js(ws, """
                (() => {
                    const sidebar = document.getElementById('sidebar');
                    const collapseBtn = document.getElementById('sidebarCollapseBtn');
                    const rect = sidebar.getBoundingClientRect();
                    return {
                        width: rect.width,
                        isCollapsed: sidebar.classList.contains('collapsed'),
                        collapseBtnTitle: collapseBtn.title
                    };
                })()
            """)
            print("[TEST 3] Expanded State:", expanded_metrics)
            assert expanded_metrics["width"] > 200, f"Expected width > 200, got {expanded_metrics['width']}"
            assert not expanded_metrics["isCollapsed"], "Sidebar .collapsed class should be removed!"
            assert "Collapse" in expanded_metrics["collapseBtnTitle"], "Button title should revert to Collapse"
            print("PASS: Test 3 - Sidebar successfully expanded back to full width via #sidebarCollapseBtn!")

            await take_screenshot(ws, "02_sidebar_expanded_via_btn.png")

            # ---------------------------------------------------------
            # TEST 4: Collapse again, then EXPAND via #sidebarBrandMini ("AF" badge)
            # ---------------------------------------------------------
            print("\n[TEST 4] Collapsing again, then expanding via #sidebarBrandMini ('AF' badge)...")
            await eval_js(ws, "document.getElementById('sidebarCollapseBtn').click()")
            time.sleep(0.5)

            is_coll = await eval_js(ws, "document.getElementById('sidebar').classList.contains('collapsed')")
            assert is_coll, "Failed to collapse"

            # Click the AF mini badge button
            await eval_js(ws, "document.getElementById('sidebarBrandMini').click()")
            time.sleep(0.5)

            brand_expand_metrics = await eval_js(ws, """
                (() => {
                    const sidebar = document.getElementById('sidebar');
                    const shell = document.getElementById('app-shell');
                    const rect = sidebar.getBoundingClientRect();
                    return {
                        width: rect.width,
                        isCollapsed: sidebar.classList.contains('collapsed'),
                        shellVisible: shell && shell.classList.contains('is-visible'),
                        hash: location.hash
                    };
                })()
            """)
            print("[TEST 4] Expanded via Mini Brand State:", brand_expand_metrics)
            assert brand_expand_metrics["width"] > 200, "Sidebar should expand when mini brand mark is clicked!"
            assert not brand_expand_metrics["isCollapsed"], "Sidebar should not be collapsed"
            assert brand_expand_metrics["shellVisible"], "App shell should remain visible (not booted to public page!)"
            assert brand_expand_metrics["hash"] != "#home", "Should NOT have navigated to public #home!"
            print("PASS: Test 4 - Sidebar successfully expanded via mini brand mark without unwanted public redirect!")

            await take_screenshot(ws, "03_sidebar_expanded_via_brand.png")

            # ---------------------------------------------------------
            # TEST 5: Topbar toggle #desktopSidebarToggle
            # ---------------------------------------------------------
            print("\n[TEST 5] Testing topbar toggle #desktopSidebarToggle...")
            await eval_js(ws, "document.getElementById('desktopSidebarToggle').click()")
            time.sleep(0.5)
            c1 = await eval_js(ws, "document.getElementById('sidebar').classList.contains('collapsed')")
            assert c1, "Topbar toggle failed to collapse"

            await eval_js(ws, "document.getElementById('desktopSidebarToggle').click()")
            time.sleep(0.5)
            c2 = await eval_js(ws, "document.getElementById('sidebar').classList.contains('collapsed')")
            assert not c2, "Topbar toggle failed to expand"
            print("PASS: Test 5 - Topbar #desktopSidebarToggle collapses and expands correctly.")

            # ---------------------------------------------------------
            # TEST 6: Keyboard shortcut Ctrl+B and '['
            # ---------------------------------------------------------
            print("\n[TEST 6] Testing Keyboard Shortcut Ctrl+B...")
            await eval_js(ws, """
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true, bubbles: true }));
            """)
            time.sleep(0.5)
            k1 = await eval_js(ws, "document.getElementById('sidebar').classList.contains('collapsed')")
            assert k1, "Ctrl+B failed to collapse"

            await eval_js(ws, """
                document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', ctrlKey: true, bubbles: true }));
            """)
            time.sleep(0.5)
            k2 = await eval_js(ws, "document.getElementById('sidebar').classList.contains('collapsed')")
            assert not k2, "Ctrl+B failed to expand"
            print("PASS: Test 6 - Keyboard shortcut Ctrl+B toggles sidebar collapse and expand smoothly.")

            # ---------------------------------------------------------
            # TEST 7: ACCORDION Menu Sections: Collapse and Expand
            # ---------------------------------------------------------
            print("\n[TEST 7] Testing Accordion Sections Collapse and Expand...")
            op_group = await eval_js(ws, """
                (() => {
                    const group = document.querySelector('.nav-accordion-group[data-section=\"operations\"]');
                    const items = group.querySelector('.nav-section-items');
                    const header = group.querySelector('.nav-section-header');
                    return {
                        isCollapsed: group.classList.contains('collapsed'),
                        expandedAttr: header.getAttribute('aria-expanded'),
                        height: items.getBoundingClientRect().height
                    };
                })()
            """)
            print("Initial Operations Accordion State:", op_group)
            assert op_group["height"] > 50, f"Expected accordion items height > 50, got {op_group['height']}"

            # Click Operations header to COLLAPSE
            print("Clicking Operations header to collapse...")
            await eval_js(ws, """
                document.querySelector('.nav-accordion-group[data-section=\"operations\"] .nav-section-header').click();
            """)
            time.sleep(0.4)

            op_collapsed = await eval_js(ws, """
                (() => {
                    const group = document.querySelector('.nav-accordion-group[data-section=\"operations\"]');
                    const items = group.querySelector('.nav-section-items');
                    const header = group.querySelector('.nav-section-header');
                    return {
                        isCollapsed: group.classList.contains('collapsed'),
                        expandedAttr: header.getAttribute('aria-expanded'),
                        height: items.getBoundingClientRect().height
                    };
                })()
            """)
            print("Collapsed Operations Accordion State:", op_collapsed)
            assert op_collapsed["isCollapsed"], "Operations group should have .collapsed"
            assert op_collapsed["expandedAttr"] == "false", "aria-expanded should be false"
            assert op_collapsed["height"] == 0, f"Expected height == 0, got {op_collapsed['height']}"

            await take_screenshot(ws, "04_operations_accordion_collapsed.png")

            # Click Operations header to EXPAND
            print("Clicking Operations header to expand...")
            await eval_js(ws, """
                document.querySelector('.nav-accordion-group[data-section=\"operations\"] .nav-section-header').click();
            """)
            time.sleep(0.4)

            op_re_expanded = await eval_js(ws, """
                (() => {
                    const group = document.querySelector('.nav-accordion-group[data-section=\"operations\"]');
                    const items = group.querySelector('.nav-section-items');
                    const header = group.querySelector('.nav-section-header');
                    return {
                        isCollapsed: group.classList.contains('collapsed'),
                        expandedAttr: header.getAttribute('aria-expanded'),
                        height: items.getBoundingClientRect().height
                    };
                })()
            """)
            print("Re-expanded Operations Accordion State:", op_re_expanded)
            assert not op_re_expanded["isCollapsed"], "Operations group should NOT have .collapsed"
            assert op_re_expanded["expandedAttr"] == "true", "aria-expanded should be true"
            assert op_re_expanded["height"] > 50, f"Expected height > 50, got {op_re_expanded['height']}"
            print("PASS: Test 7 - Operations accordion section collapsed and expanded flawlessly!")

            await take_screenshot(ws, "05_operations_accordion_expanded.png")

            # ---------------------------------------------------------
            # TEST 8: Rail Section Divider click expands sidebar
            # ---------------------------------------------------------
            print("\n[TEST 8] Testing Rail Section Divider click to expand sidebar...")
            # Collapse sidebar first
            await eval_js(ws, "toggleSidebarCollapse(true)")
            time.sleep(0.4)
            assert await eval_js(ws, "document.getElementById('sidebar').classList.contains('collapsed')")

            # Click section header/divider while in rail mode
            await eval_js(ws, """
                document.querySelector('.nav-accordion-group[data-section=\"fleet\"] .nav-section-header').click();
            """)
            time.sleep(0.5)

            rail_click_expand = await eval_js(ws, """
                (() => {
                    const sidebar = document.getElementById('sidebar');
                    const fleetGroup = document.querySelector('.nav-accordion-group[data-section=\"fleet\"]');
                    return {
                        sidebarCollapsed: sidebar.classList.contains('collapsed'),
                        fleetCollapsed: fleetGroup.classList.contains('collapsed')
                    };
                })()
            """)
            print("Rail divider click result:", rail_click_expand)
            assert not rail_click_expand["sidebarCollapsed"], "Sidebar should expand on rail section click!"
            assert not rail_click_expand["fleetCollapsed"], "Fleet section should be open"
            print("PASS: Test 8 - Clicking section divider in rail mode expanded the sidebar and opened the section!")

            await take_screenshot(ws, "06_final_verified_state.png")

            print("\n========================================================")
            print("ALL 8 IN-BROWSER INTERACTIVE TESTS PASSED 100% PERFECTLY!")
            print("========================================================")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        if os.path.exists(PROFILE_DIR):
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(run_tests())
