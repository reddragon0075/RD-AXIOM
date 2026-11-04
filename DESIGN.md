# AXIOM FLEET ENTERPRISE DESIGN SYSTEM SPECIFICATION (`DESIGN.md`)
*Indecab-Inspired Minimalist, High-Contrast Light & Brand-Navy Flagship Edition*

This document defines the visual design system, color tokens, typography hierarchy, component architectures, and responsive layout specifications for the public web experience of **Axiom Fleet** (`https://axiommobility.vercel.app/`), paired with the official **AXIOM FLEET** brand identity.

---

## 1. BRAND IDENTITY & LOGO TOKENS

### A. Official Brand Logo
- **Asset Path:** `fleetline-mvp/axiom-fleet-logo.png`
- **Visual Composition:**
  - **Road Icon (`A` Mark):** Electric Blue (`#0066FF`) fading into bright Teal (`#00A896`) along a white perspective road divider.
  - **Wordmark (`AXIOM`):** Deep Navy-Black (`#0A1628`), bold geometric sans-serif with distinct chevron `A`.
  - **Subtitle (`FLEET`):** Electric Blue (`#0066FF`), spaced uppercase tabular tracking.

### B. Contrast Mandate (WCAG AAA Compliance)
- **Zero Low-Contrast Text:** No white text on white/light backgrounds. All primary headlines on light sections are deep navy `#0A1628`.
- **Canvas Decluttering:** 3D floating city coordinate canvas (`#axiom-network-globe`) is eliminated from behind text blocks, ensuring 100% legibility on all display densities.

---

## 2. STRICT COLOR & SURFACE TOKENS

```css
:root {
  /* Surfaces & Backgrounds */
  --bg-page: #FFFFFF;                 /* Pure Crisp White base */
  --bg-section-alt: #F4F7FB;          /* Soft Ice-Slate alternating bands */
  --bg-navy-dark: #0A1628;            /* Deep Axiom Brand Navy (Dark Cockpit & Footer) */
  --bg-card: #FFFFFF;                 /* Card Surface */

  /* Text & Typography */
  --text-heading: #0A1628;             /* Deep Axiom Navy-Black (Primary Headlines) */
  --text-body: #334155;                /* High-Contrast Slate-700 for Body Copy */
  --text-muted: #64748B;               /* Slate-500 for secondary captions */

  /* Brand Accents */
  --brand-blue: #0066FF;               /* Axiom Primary Electric Blue */
  --brand-blue-hover: #0052CC;         /* Hover state */
  --brand-teal: #00A896;               /* Road-Swoosh Teal */
  --brand-gradient: linear-gradient(135deg, #0066FF 0%, #00B4B4 100%);
  --brand-text-gradient: linear-gradient(90deg, #0052CC 0%, #008B8B 100%);

  /* Borders & Shadows */
  --border-clean: #E2E8F0;             /* Crisp 1px Card Border */
  --border-subtle: #F1F5F9;            /* Hairline divider */
  --shadow-minimal: 0 10px 30px -10px rgba(10, 22, 40, 0.07);
  --shadow-hover: 0 20px 40px -12px rgba(10, 22, 40, 0.12);

  /* Functional Status Colors */
  --status-emerald: #059669;           /* Active / Settled / Profitable */
  --status-emerald-bg: #ECFDF5;
  --status-amber: #D97706;             /* Escrow Hold / Pending Audit */
  --status-amber-bg: #FEF3C7;
  --status-blue-bg: #EFF6FF;
}
```

---

## 3. TYPOGRAPHY HIERARCHY

- **Display & Section Headings (`h1`, `h2`, `h3`):**
  - Font: `'Plus Jakarta Sans'`, `'Inter'`, system-ui, sans-serif
  - Weight: `800` (Extra Bold)
  - Tracking: `-0.03em`
  - Color: `#0A1628`
  - Highlighted Gradient Spans: `background: linear-gradient(90deg, #0052CC, #008B8B); -webkit-background-clip: text; -webkit-text-fill-color: transparent;`
- **Body & Explanatory Copy:**
  - Font: `'Plus Jakarta Sans'`, `'Inter'`, sans-serif
  - Weight: `400` / `500`
  - Line-Height: `1.6`
  - Color: `#334155`
- **Financial & Telemetry Data (ODOMETERS, GST IRN, ₹ AMOUNTS):**
  - Font: `'JetBrains Mono'`, monospace
  - Feature: `font-variant-numeric: tabular-nums`

---

## 4. SECTION-BY-SECTION ARCHITECTURAL BREAKDOWN

### Section 1: Clean Minimalist Sticky Top Navbar
- **Background:** Crisp White (`rgba(255, 255, 255, 0.95)`) with `backdrop-filter: blur(12px)` and 1px border (`#E2E8F0`).
- **Brand:** Official `axiom-fleet-logo.png` (132x38px).
- **Navigation Items:**
  1. `For Corporates` -> `#for-corporates`
  2. `For Car Rentals` -> `#for-car-rentals`
  3. `Mobile Apps` -> `#driver-app`
  4. `Partner Network` -> `#axiom-network`
  5. `ROI & Fare Calculator` -> `#calculator`
- **Actions:**
  - `Sign In` -> Opens authentication screen `#auth-screen`.
  - `Book Enterprise Demo` -> Smooth scrolls to `#contact`.

### Section 2: High-Contrast Hero & Cockpit Preview
- **Eyebrow Pill:** `#EFF6FF` pill badge with `#0066FF` text: `"✨ NEW: AI WhatsApp Booking, Automated Odometer Audit & Margin Protection"`.
- **Primary Headline:** `"The Operating System for Modern Fleet & Corporate Mobility."`
- **Lead Subheading:** High-contrast slate copy covering automated dispatch, GPS route audit, dual-ledger billing, and instant partner waterfalls.
- **Lead Quick-Input:** Mobile/Email capture pill that pre-fills the enterprise request form and smoothly scrolls to contact.
- **Interactive Cockpit Preview:** Dark navy (`#0A1628`) container previewing live platform telemetry with 4 interactive tabs:
  - *Tab 1: Live Dispatch & Telemetry* (Duty Slip #8831, MG Road -> KIAL route verification).
  - *Tab 2: Billing & Escrow Release* (Completed trip #9041, interactive simulated escrow release toggle).
  - *Tab 3: Partner Network Exchange* (Masked corporate identity, rate card protection).
  - *Tab 4: Predictive Financial Intelligence* (30-day corporate spend & vendor revenue forecast).

### Section 3: Powering Enterprises & Corporates (Bento Grid on `#F4F7FB`)
- High-contrast 2x2 grid tailored for corporate travel desks, procurement heads, and HR admins:
  1. Automated Employee Duty Allocation & Rostering.
  2. 3-Way GPS, Toll & Odometer Audit (Zero Bill Inflation).
  3. Strict SLA & Safety Guardrails (POSH, SOS, panic alerts).
  4. Unified Corporate Invoicing & GST Compliance.

### Section 4: Powering Car Rental Companies & Fleet Vendors (Grid on `#FFFFFF`)
- 3x2 feature grid for fleet operators, dispatchers, and accountants:
  1. Instant WhatsApp AI Booking & Smart Dispatch.
  2. Dual-Ledger Financial Reconciliation (Client bill vs Vendor payout).
  3. Timed Partner Waterfall Exchange (Zero-deadlock overflow handling).
  4. Real-Time Vehicle Maintenance & Insurance Trackers.
  5. Instant Driver Settlement & FASTag Toll Pass-Through.
  6. Multi-City Corporate Contract Management.

### Section 5: Dedicated Mobile App Showcase (Dual Phones on `#F4F7FB`)
- Realistic CSS smartphone frames showcasing:
  - **Phone 1 (Driver Mobile App):** Live turn-by-turn route, start/stop digital duty slip with odometer photograph verification and OTP release.
  - **Phone 2 (Vendor Pocket App):** Real-time gross bookings counter (₹4,82,500), active vehicles on duty (42/48), and instant 1-tap partner dispatch.

### Section 6: The Axiom Partner Network (3 Pillars on `#FFFFFF`)
- High-contrast 3-column enterprise architecture:
  1. *Trust-First Confidentiality:* Sub-vendors never see corporate client identity or contract rate cards.
  2. *Escrow Payout Guarantee:* T+1 automated payouts directly into vendor bank accounts upon duty verification.
  3. *Zero Lead Waste:* Overflow duties automatically route across verified peer operators across 40+ Indian airports.

### Section 7: Calculate the Difference (Interactive Sliders on `#F4F7FB`)
- **Part A (Monthly ROI Calculator):**
  - Input: Average duties completed per month (100 to 10,000 via `#roi-duties-slider`).
  - Output: Billing & odometer leakage saved (₹), dispatcher hours saved, paper duty slips eliminated, faster invoice turnaround days.
- **Part B (Auto-Slab & Margin Guardrail Simulator):**
  - Inputs: Practical trip distance (km) and trip duration (hrs).
  - Output: Automated package selection (4Hr/40Km vs 8Hr/80Km), client receivable, vendor payout, and guaranteed profit margin badge.

### Section 8: Enterprise Request & Indecab-Inspired Minimalist Footer
- **Lead Capture Form:** 2-column clean card submitting directly to `POST /api/v1/public/prospect-capture`.
- **Footer Architecture (`#0A1628` Dark Navy):**
  - Official inverted brand logo (`axiom-fleet-logo.png`).
  - Company value summary and contact email/phone.
  - 4 structured navigation columns: *Solutions*, *Platform & Apps*, *Partner Network*, *Enterprise Support*.
  - Bottom bar: Copyright, Made for Indian Corporate Mobility, and Legal links.

---

## 5. REVENUE & DISPATCH INVARIANTS

1. **Client Identity Anonymity:** When duties are broadcasted to the Partner Network, corporate identities are strictly masked.
2. **Escrow Hold & Margin Protection:** Payouts remain in escrow hold until digital duty slip verification (GPS + Odometer + Toll audit).
3. **Zero-Build Architecture:** Entire landing page runs with zero build step, zero npm bundles, vanilla ES6+, HTML5, and CSS3.
