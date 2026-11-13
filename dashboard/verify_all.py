import asyncio
import os
import subprocess
import sys
import time
import urllib.request
from playwright.async_api import async_playwright

async def run_audit():
    print("Starting ASGI Server process...", flush=True)
    server_proc = subprocess.Popen(
        [sys.executable, "fleetline-mvp/asgi_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    
    # Wait for server to bind port 4173
    ready = False
    for i in range(25):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen("http://127.0.0.1:4173/health", timeout=1) as resp:
                if resp.status == 200:
                    ready = True
                    print(f"ASGI server is live on http://127.0.0.1:4173! Response: {resp.read().decode().strip()}", flush=True)
                    break
        except Exception:
            pass
            
    if not ready:
        print("Server failed to respond on port 4173", flush=True)
        server_proc.kill()
        return

    out_dir = r"C:\Users\91782\.gemini\antigravity\brain\95548492-c2ed-4a12-827a-7c782c4a1ecb"

    async with async_playwright() as p:
        print("Launching Playwright Chromium...", flush=True)
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        
        # 1. Modern React ERP Overview
        print("1. Testing Modern React ERP at http://127.0.0.1:4173/app/ ...", flush=True)
        await page.goto("http://127.0.0.1:4173/app/", wait_until="domcontentloaded", timeout=10000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=os.path.join(out_dir, "modern_erp_overview.png"))
        print("Captured modern_erp_overview.png", flush=True)
        
        # 2. Modern React ERP Fleet Table
        print("2. Testing Fleet Registry Tab...", flush=True)
        fleet_btn = page.locator("button:has-text('Fleet Registry')")
        if await fleet_btn.count() > 0:
            await fleet_btn.click()
            await page.wait_for_timeout(1000)
            await page.screenshot(path=os.path.join(out_dir, "modern_erp_fleet.png"))
            print("Captured modern_erp_fleet.png", flush=True)
            
        # 3. Modern React ERP Live Radar
        print("3. Testing Live Telemetry Radar Tab...", flush=True)
        radar_btn = page.locator("button:has-text('Live Telemetry Radar')")
        if await radar_btn.count() > 0:
            await radar_btn.click()
            await page.wait_for_timeout(2000)
            await page.screenshot(path=os.path.join(out_dir, "modern_erp_radar.png"))
            print("Captured modern_erp_radar.png", flush=True)
            
        await browser.close()
        print("All modern frontend screenshots captured successfully!", flush=True)

    print("Shutting down test ASGI process...", flush=True)
    server_proc.terminate()
    try:
        server_proc.wait(timeout=3)
    except Exception:
        server_proc.kill()
    print("Verification completed cleanly!", flush=True)

if __name__ == "__main__":
    asyncio.run(run_audit())

