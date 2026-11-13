import asyncio
import sys
import traceback
from playwright.async_api import async_playwright

async def main():
    try:
        async with async_playwright() as p:
            print("Launching browser...", flush=True)
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            
            print("Navigating to http://127.0.0.1:5173 ...", flush=True)
            await page.goto("http://127.0.0.1:5173", wait_until="domcontentloaded", timeout=10000)
            await page.wait_for_timeout(2500)
            
            out_dir = r"C:\Users\91782\.gemini\antigravity\brain\95548492-c2ed-4a12-827a-7c782c4a1ecb"
            await page.screenshot(path=f"{out_dir}\\react_dashboard_overview.png")
            print("Saved react_dashboard_overview.png", flush=True)
            
            # Click Fleet
            fleet_btn = page.locator("button:has-text('Fleet Registry')")
            if await fleet_btn.count() > 0:
                await fleet_btn.click()
                await page.wait_for_timeout(1500)
                await page.screenshot(path=f"{out_dir}\\react_dashboard_fleet.png")
                print("Saved react_dashboard_fleet.png", flush=True)
            
            # Click Live Radar
            radar_btn = page.locator("button:has-text('Live Telemetry Radar')")
            if await radar_btn.count() > 0:
                await radar_btn.click()
                await page.wait_for_timeout(2000)
                await page.screenshot(path=f"{out_dir}\\react_dashboard_radar.png")
                print("Saved react_dashboard_radar.png", flush=True)
                
            await browser.close()
            print("ALL DONE!", flush=True)
    except Exception as e:
        print("Error:", e, flush=True)
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
