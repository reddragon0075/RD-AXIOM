import time
import os
from playwright.sync_api import sync_playwright

def verify_live():
    print("Beginning fresh incognito E2E verification...")

    with sync_playwright() as p:
        # Launch Chrome with a completely fresh incognito context
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        logs = []
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda err: logs.append(f"[PAGE ERROR] {err}"))

        # -------------------------------------------------------------
        # TEST 1: Method A Direct Login (Email + Password)
        # -------------------------------------------------------------
        print("\n--- TEST 1: Method A Sign-In on Live Vercel ---")
        url = "https://axiommobility.vercel.app/#login"
        print(f"Navigating to {url} ...")
        page.goto(url, wait_until="networkidle", timeout=45000)
        time.sleep(3)

        # Clear any stale localStorage just to ensure clean state
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Make sure login form is visible
        page.evaluate("() => { if (typeof showLogin === 'function') showLogin(false); }")
        time.sleep(1)

        print("Locating email & password fields...")
        page.wait_for_selector("#login-email", timeout=10000)
        
        print("Entering email: reddragon0075@gmail.com")
        page.fill("#login-email", "reddragon0075@gmail.com")
        
        print("Entering password: motion2026")
        page.fill("#login-password", "motion2026")

        # Capture pre-submit screenshot
        pre_login_pic = "C:/Users/91782/.gemini/antigravity/brain/95548492-c2ed-4a12-827a-7c782c4a1ecb/test_login_form_filled.png"
        page.screenshot(path=pre_login_pic)
        print(f"Pre-submit screenshot: {pre_login_pic}")

        print("Clicking 'Enter workspace ->' button...")
        page.click("#login-form button[type='submit']")

        # Wait for workspace transition and data hydration
        print("Waiting for workspace to load and hydrate operational data...")
        time.sleep(6)

        is_app_mode = page.evaluate("() => document.documentElement.classList.contains('is-app-mode')")
        auth_visible = page.is_visible("#auth-screen")
        app_shell_visible = page.is_visible("#app-shell")
        user_storage = page.evaluate("() => localStorage.getItem('axiomfleet_user')")
        login_err = page.inner_text("#login-error") if page.is_visible("#login-error") else ""

        print(f"Result URL: {page.url}")
        print(f"is-app-mode active: {is_app_mode}")
        print(f"Auth screen hidden: {not auth_visible}")
        print(f"App shell visible: {app_shell_visible}")
        print(f"Stored user: {user_storage}")
        print(f"Login error text: '{login_err}'")

        # Navigate to #bookings to check data grid
        page.evaluate("() => { window.location.hash = '#bookings'; }")
        time.sleep(2)
        booking_rows = page.evaluate("() => document.querySelectorAll('#bookings table tbody tr, .booking-row').length")
        print(f"Booking rows loaded: {booking_rows}")

        # Capture post-login proof screenshot
        post_login_pic = "C:/Users/91782/.gemini/antigravity/brain/95548492-c2ed-4a12-827a-7c782c4a1ecb/test_login_success_proof.png"
        page.screenshot(path=post_login_pic, full_page=True)
        print(f"Post-login workspace proof screenshot: {post_login_pic}")

        test1_passed = is_app_mode and app_shell_visible and not auth_visible and len(login_err) == 0

        # -------------------------------------------------------------
        # TEST 2: Create Account (Sign-up Form)
        # -------------------------------------------------------------
        print("\n--- TEST 2: Create Account / Sign-Up on Live Vercel ---")
        page2 = context.new_page()
        page2.goto("https://axiommobility.vercel.app/#login", wait_until="networkidle", timeout=30000)
        time.sleep(2)
        page2.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        page2.goto("https://axiommobility.vercel.app/#login", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Open auth screen and switch to signup mode
        page2.evaluate("() => { if (typeof showLogin === 'function') showLogin(false); if (typeof setAuthMode === 'function') setAuthMode('signup'); }")
        time.sleep(1)

        print("Waiting for signup-name field...")
        page2.wait_for_selector("#signup-name", timeout=10000)

        print("Filling Create Account registration form...")
        page2.fill("#signup-name", "Abhijith Vijayan")
        page2.fill("#signup-email", "reddragon0075@gmail.com")
        page2.fill("#signup-phone", "+917829885737")
        page2.select_option("#signup-city", "Bengaluru")
        page2.evaluate("() => { const tz = document.getElementById('signup-timezone'); if (tz && !tz.value) tz.value = 'Asia/Kolkata'; }")
        page2.fill("#signup-organization", "goblr")
        page2.fill("#signup-password", "motion2026")

        signup_pre_pic = "C:/Users/91782/.gemini/antigravity/brain/95548492-c2ed-4a12-827a-7c782c4a1ecb/test_signup_form_filled.png"
        page2.screenshot(path=signup_pre_pic)
        print(f"Pre-signup screenshot: {signup_pre_pic}")

        print("Submitting Create Account form...")
        page2.click("#signup-form button[type='submit']")
        time.sleep(5)

        signup_is_app = page2.evaluate("() => document.documentElement.classList.contains('is-app-mode')")
        signup_err = page2.inner_text("#signup-error") if page2.is_visible("#signup-error") else ""
        print(f"Signup Result URL: {page2.url}")
        print(f"Signup is-app-mode: {signup_is_app}")
        print(f"Signup error: '{signup_err}'")

        signup_post_pic = "C:/Users/91782/.gemini/antigravity/brain/95548492-c2ed-4a12-827a-7c782c4a1ecb/test_signup_success_proof.png"
        page2.screenshot(path=signup_post_pic, full_page=True)
        print(f"Post-signup proof screenshot: {signup_post_pic}")

        test2_passed = signup_is_app and len(signup_err) == 0

        print("\n=== CONSOLE LOGS (last 15) ===")
        for l in logs[-15:]:
            print(" ", l)

        browser.close()

        print("\n================ TEST SUMMARY ================")
        print(f"Method A Direct Sign-In (reddragon0075@gmail.com / motion2026): {'PASS' if test1_passed else 'FAIL'}")
        print(f"Create Account Flow (Abhijith Vijayan / goblr): {'PASS' if test2_passed else 'FAIL'}")
        print("==============================================")
        return test1_passed and test2_passed

if __name__ == "__main__":
    success = verify_live()
    exit(0 if success else 1)
