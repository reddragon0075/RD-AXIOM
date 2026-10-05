# Axiom Mobility

Axiom Mobility is an enterprise-grade car rental and fleet logistics operating platform engineered for multi-tenant B2B corporate travel, vendor operations, driver field execution, and network exchange clearing.

---

## 📚 Core Technical Documentation

- **[Technology Stack & System Architecture](TECH_STACK.md)**: Exhaustive breakdown of frontend, backend, database, Supabase cloud parity, security standards, and directory layouts.
- **[Fleetline MVP Subsystem](fleetline-mvp/README.md)**: Detailed feature scope, MVP release gates, and implementation guide for the `fleetline-mvp` application.
- **[Technical PRD](.scratch/prd.md)**: Full business and technical requirements specification.

---

## ⚡ Quick Start

### 1. Run the Local Sovereign Runtime
The local development server requires only Python 3.10+ and standard library modules (no `pip install` or `npm install` needed):

```bash
cd fleetline-mvp
python -X utf8 server.py
```

Open your browser at `http://127.0.0.1:4173/`.

### 2. Run the Verification Suites
Run the automated test harness:

```bash
cd fleetline-mvp

# Run the 139-check system regression suite
python -X utf8 regression_check.py

# Run all 36 domain smoke test suites
python -X utf8 masters_smoke_test.py
python -X utf8 supabase_contract_test.py
```

---

## 🏛️ Architecture Highlights

- **Dual-Runtime Compatibility**: Develop dependency-free locally with SQLite 3 (WAL mode) or deploy seamlessly to PostgreSQL on Supabase with Row-Level Security (RLS).
- **Zero-Build Frontend**: Vanilla ES6+ SPA architecture with instant load, PWA capabilities, and an offline-first synchronization queue.
- **Enterprise Multi-Tenancy**: Kernel-enforced tenant isolation with immutable audit logging and financial maker-checker approvals.
