"""Static contract checks for the Axiom Fleet Driver mobile vertical slice."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PWA = ROOT / "driver-app"
NATIVE = ROOT / "mobile-driver"

def check(label: str, condition: bool) -> None:
    if not condition:
        raise SystemExit(f"FAIL {label}")
    print(f"PASS {label}")

pwa = (PWA / "index.html").read_text()
app = (NATIVE / "App.tsx").read_text()
api = (NATIVE / "src" / "api.ts").read_text()
location_task = (NATIVE / "src" / "locationTask.ts").read_text()
server = (ROOT / "server.py").read_text()
domain = (ROOT / "backend_domain.py").read_text()
extended = (ROOT / "backend_extended.py").read_text()
manifest = (PWA / "manifest.json").read_text()

check("driver PWA exists", (PWA / "index.html").is_file())
check("driver PWA has sign-in and no demo entry", "Open my duty day" in pwa and "Preview driver mode" not in pwa and "demo duty" not in pwa.lower())
check("driver PWA has offline queue and sync center", "axiomfleet_driver_queue_v1" in pwa and "Sync center" in pwa and "/api/sync/replay" in pwa)
check("driver PWA has proof, expense, masked call and SOS controls", "Close with proof" in pwa and "Add expense" in pwa and "Masked call" in pwa and "Safety / SOS" in pwa)
check("driver PWA has install manifest and service worker", (PWA / "manifest.json").is_file() and (PWA / "sw.js").is_file() and "serviceWorker" in pwa)
check("native driver app scaffold exists", (NATIVE / "App.tsx").is_file() and (NATIVE / "package.json").is_file() and (NATIVE / "app.json").is_file())
check("native driver app covers duty lifecycle and location", "transitionDuty" in app and "bufferLocation" in app and "startBackgroundLocation" in app and "Complete with proof" in app)
check("background location is permission-gated and durable", "requestBackgroundPermissionsAsync" in location_task and "startLocationUpdatesAsync" in location_task and "AsyncStorage" in location_task and "flushLocationBuffer" in location_task and "idempotencyKey" in location_task)
check("native driver app covers camera and signature proof", "CameraView" in app and "SignatureScreen" in app and "Capture photo" in app and "Add signature" in app)
check("native driver app covers offline replay and safety", "AsyncStorage" in app and "replay(" in app and "sendSos" in app)
check("native driver app registers push notifications", "registerPushDevice" in app and "registerDevice" in api and "sos_alert" in app)
check("native API stores mobile token and uses bearer auth", "expo-secure-store" in api and "Authorization" in api and "access_token" in api)
check("local replay handles proof, expense and SOS operations", 'operation_name in {"proof", "capture_proof"}' in domain and 'operation_name == "expense"' in domain and 'operation_name == "sos"' in domain)
check("backend queues assignment and SOS push deliveries", "_queue_push_notification" in domain and "duty_reassigned" in extended and "sos_alert" in extended)
check("local server supports bearer sessions", "authorization.lower().startswith(\"bearer \")" in server and '"access_token": session' in server)
print("RESULT driver mobile contracts passed")
