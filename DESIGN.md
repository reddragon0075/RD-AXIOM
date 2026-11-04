# AXIOM MOBILITY DESIGN SYSTEM SPECIFICATION (`DESIGN.md`)
*Refero + Scrolltide + Supahero Flagship Edition (v2.6 Enterprise)*

This document defines the visual tokens, typography hierarchy, component architectures, and interaction physics for the public landing & marketing experience of **Axiom Mobility (Fleetline)** (`https://axiommobility.vercel.app/`).

---

## 1. DESIGN TOKENS (REFERO SPECIFICATION)

### A. Color Palette ("Obsidian Mobility & FinTech Emerald/Amber")
```css
:root {
  /* Surface & Canvas Tokens */
  --bg-canvas: #06080D;                /* Deep Obsidian Carbon base */
  --bg-surface-1: #0D111A;             /* Elevated Bento Card Base */
  --bg-surface-2: #141B27;             /* Elevated Interactive Elements & Insets */
  --bg-surface-glass: rgba(17, 23, 36, 0.68); /* Frosted Glass Base */
  --bg-surface-glass-heavy: rgba(10, 14, 23, 0.88); /* Heavy Frosted Layer */

  /* Hairlines & Specular Borders */
  --border-subtle: rgba(255, 255, 255, 0.08); /* 1px Specular Hairline */
  --border-medium: rgba(255, 255, 255, 0.14); /* Focused Element Border */
  --border-highlight: rgba(16, 185, 129, 0.45); /* Emerald Hover Glow */
  --border-indigo: rgba(99, 102, 241, 0.40);   /* TimesFM AI Accent Glow */

  /* Text & Readability Hierarchy */
  --text-primary: #F8FAFC;              /* Crisp Alabaster (Headings, Active Data) */
  --text-secondary: #94A3B8;            /* Muted Slate (Descriptions, Body) */
  --text-tertiary: #64748B;             /* Sub-captions, Timestamps, Inactive Tabs */

  /* Semantic Accent Channels */
  --accent-emerald: #10B981;            /* Dual-Ledger Profit / Live Active Fleet */
  --accent-emerald-glow: rgba(16, 185, 129, 0.22);
  --accent-indigo: #6366F1;             /* TimesFM AI / Partner Network Waterfall */
  --accent-indigo-glow: rgba(99, 102, 241, 0.22);
  --accent-amber: #F59E0B;              /* SLA Guardrail / Treasury Float Hold */
  --accent-amber-glow: rgba(245, 158, 11, 0.22);
  --accent-cyan: #06B6D4;               /* OSM Road Snapping / Odometer Audit */
  --accent-rose: #F43F5E;               /* Variance Alerts / Night Shift Lock */

  /* Gradients */
  --grad-emerald: linear-gradient(135deg, #10B981 0%, #059669 100%);
  --grad-indigo: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%);
  --grad-glass: linear-gradient(180deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.01) 100%);
  --grad-metallic: linear-gradient(180deg, #FFFFFF 0%, #94A3B8 60%, #334155 100%);
}
```

### B. Typography Hierarchy
- **Display Headlines:** `'Plus Jakarta Sans'`, `'Inter'`, -apple-system, sans-serif
  - `font-weight: 700`, `letter-spacing: -0.035em`, `line-height: 1.06`
  - Used for hero statement, section titles, and monumental impact copy.
- **Editorial Accent Clauses (Scrolltide Style):** `'Instrument Serif'`, `'Playfair Display'`, Georgia, serif
  - `font-style: italic`, `font-weight: 400`
  - Used for emotional focal points within headlines (e.g., *"Built for the fleets that move *corporate India*."*).
- **Financial & Telemetry Data:** `'JetBrains Mono'`, 'SF Mono', Consolas, monospace
  - `font-variant-numeric: tabular-nums`
  - Mandatory for all currency figures (`₹`), odometers (`84.0 km`), SLA percentages (`99.98%`), and GST IRN / hash tokens.
- **Body & Microcopy:** `'Inter'`, system-ui, sans-serif
  - `font-weight: 400` and `500`, `letter-spacing: -0.011em`, `line-height: 1.6`.

---

## 2. INTERACTION PHYSICS & MICRO-ANIMATIONS

### A. 3D Perspective & Hardware Acceleration
- **Stage Perspective:** `perspective: 1400px; transform-style: preserve-3d;`
- **Hero Command Center Tilt:** Starts at `rotateX(14deg) scale(0.94)` and interpolates to `rotateX(0deg) scale(1.0)` between scroll delta `0px` and `400px` via a `requestAnimationFrame` damping curve.
- **Specular Hover Tracking:** Bento cards track cursor `(clientX, clientY)` to compute dynamic radial sheen:
  `background: radial-gradient(600px circle at var(--mouse-x) var(--mouse-y), rgba(255,255,255,0.06), transparent 40%)`.

### B. 60 FPS HTML5 `<canvas>` Corridors
- The `<canvas id="axiom-network-globe">` renders a live particle/arc network representing the six core enterprise mobility corridors:
  1. **Bengaluru** (`12.9716° N, 77.5946° E`)
  2. **Mumbai** (`19.0760° N, 72.8777° E`)
  3. **Delhi NCR** (`28.6139° N, 77.2090° E`)
  4. **Hyderabad** (`17.3850° N, 78.4867° E`)
  5. **Chennai** (`13.0827° N, 80.2707° E`)
  6. **Pune** (`18.5204° N, 73.8567° E`)
- Arcs pulse with glowing traveling photons (`--accent-emerald` for confirmed corporate charters, `--accent-indigo` for partner network exchange waterfall hops).
- Micro-parallax responds to mouse movement with subtle gyro-damping.

---

## 3. COMPONENT ARCHITECTURES

### 1. Floating Glass Command Navbar
- Centered container (`max-width: 1200px`), `position: fixed; top: 16px; border-radius: 9999px`.
- Frosted glass: `backdrop-filter: blur(20px) saturate(160%)`, 1px top highlight border.
- Clean executive links: `Billing & Margins`, `Partner Network`, `GPS & Odometer Audit`, `Cash-Flow Forecast`, `Live Calculator`.
- Integrated Quick-Demo Role Switcher (`[Sign In / Demo Role ▾]`) allowing direct one-click authentication into:
  - **Super-Admin / Axiom HQ Console** (`reddragon0075@gmail.com`)
  - **Fleet Operator Command Deck** (`Zion Travels`)
  - **Corporate Travel Desk** (`Zenith Aerospace`)
  - **Mobile Driver / Pocket App**

### 2. "Try It Live" Interactive Widget Strip
- **Smart WhatsApp Booking Intake:** Instant AI extraction that transforms unstructured WhatsApp booking text into structured dispatch tokens (`Passenger`, `Corporate Account`, `Vehicle Class`, `Verified Route`, `Optimized Tariff Package`) in `<400ms`.
- **Auto-Slab Optimizer & Margin Guardrail:** Real-time dual slider (`Distance: 20-160 km`, `Duration: 2-12 hrs`) calculating:
  - Practical Client Receivable (`₹`)
  - Sub-Vendor Payable (`₹`)
  - Net Margin Protected (`₹` and `%`)
  - Auto-upgrade threshold flag (`4Hr/40Km` vs `8Hr/80Km`).

### 3. Scrolltide Ledger Bento (6 Cards)
1. **Wide Card 1 (Span 8):** Dual-Ledger Billing with interactive `[Auto-Release] / [Hold Float]` toggle.
2. **Tall Card 2 (Span 4):** 3-Way GPS & Odometer Route Auditor (`Driver Odometer 84 km` vs `GPS 71 km` vs `Verified Route 73.2 km`).
3. **Card 3 (Span 4):** White-Label Partner Fleet Network (`Wave 1: Platinum` -> `Wave 2: Gold` -> `Spot Exchange`).
4. **Card 4 (Span 4):** Mobile Dispatcher & 2-tap cab assignment with physical paper duty sheet scanner.
5. **Card 5 (Span 4):** Axiom Cash-Flow & Demand Forecasting (`p10 / p50 / p90` revenue quantile chart).
6. **Full-Width Card 6 (Span 12):** Enterprise Compliance (POSH 20:00-06:00 guard lock, Tally Prime XML, GST e-invoicing, 1-click historical Excel/CSV migration).

### 4. Competitive Benchmark Matrix
High-contrast glass comparison matrix comparing Axiom against Indecab, MoveInSync / Routematic, and Legacy Excel/Taski across Dual-Ledger margins, 3-way route audits, partner waterfalls, and predictive forecasts.

### 5. Signal Form CTA Band & Monumental Footer
- Integrated Prospect Onboarding Form wired to `POST /api/v1/public/prospect-capture`.
- Full-width metallic gradient wordmark (`AXIOM MOBILITY`) reflecting cursor position.

---

## 4. INVARIANTS & INTEGRITY RULES
1. **Zero-Build Architecture:** All scripts must run natively in the browser without node build steps or transpilation.
2. **Auth Isolation:** `#app-shell` and `#public-site` state switches via `document.documentElement.classList.toggle('is-app-mode')` and `showApp()` must remain strictly isolated. No modifications to authenticated business logic, database migrations, or test harnesses.
3. **Accessibility:** All inputs must have associated labels, ARIA landmarks, keyboard navigation support, and fallbacks for `prefers-reduced-motion`.
