# Axiom Fleet Enterprise SaaS ERP Dashboard

Production-grade, high-volume Enterprise SaaS frontend built with **React 19 + TypeScript + Vite + Tailwind CSS + TanStack Query + Leaflet**.

Designed to interface directly with the Axiom Fleet FastAPI ASGI backend engine (`http://localhost:4173`).

---

## 🚀 Key Capabilities

- **Executive Operations Cockpit**: Real-time KPI counters (active duties, on-duty fleet, active drivers, monthly billable run-rate, telemetry bus status).
- **Live Fleet Registry**: Searchable, filterable vehicle registry with speed telemetry, driver assignments, and live status badges.
- **WebSocket GPS Radar (`/ws/telemetry`)**: Bi-directional live telemetry radar streaming real-time driver coordinates and speed with automated fallback ping simulator.
- **FastAPI ASGI Integration**: Pre-configured Vite proxy forwarding `/api`, `/ws`, and `/health` requests to `http://127.0.0.1:4173`.
- **Zero Cost / 100% Free**: Built purely on MIT / Apache-2.0 open-source packages. Zero commercial subscription requirements.

---

## 🛠️ Development & Build

### Install Dependencies
```bash
npm install
```

### Run Local Vite Dev Server (Hot Module Reload)
```bash
npm run dev
# Running on http://localhost:5173/
```

### Build Production Bundle
```bash
npm run build
# Compiles optimized static assets to dashboard/dist/ in ~1.7s
```

---

## 🌐 Unified FastAPI ASGI Serving

When built, the production bundle in `dist/` is automatically mounted and served by the FastAPI ASGI server:

- **React SaaS ERP**: `http://localhost:4173/app/`
- **Flagship Multi-Portal Prototype**: `http://localhost:4173/`
- **Driver Cockpit**: `http://localhost:4173/driver-app/`
- **OpenAPI Swagger Docs**: `http://localhost:4173/docs`
- **Live Telemetry WebSocket**: `ws://localhost:4173/ws/telemetry`
