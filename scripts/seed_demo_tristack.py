#!/usr/bin/env python3
"""Axiom Mobility (Fleetline) Tri-Stack Realistic Demo Data Seed Script.

Idempotently seeds:
1. 5 Corporate Clients (with RAC slab & ETS shift zone rate cards)
2. 8 Partner Vendors (Platinum, Gold, Silver/Demoted, Trial)
3. 25 Duties (In Progress, Completed, Unallotted, 3-Way Distance Holds, Auto-Slab Upgrades, POSH Verified)
4. 15 Webhook Audit Logs (12 OK with redacted PII + 3 Failed ready for 1-click Replay)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "axiom_fleet.sqlite3"


def seed_demo_data(conn: sqlite3.Connection) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat()
    org_id = "org_tenant_169"

    # 1. SEED 8 FLEET VENDORS IN tenant_subscriptions, tenant_wallets, tenant_feature_flags
    vendors = [
        (169, "ten_zion_169", "Zion Travels", "GROWTH", "ACTIVE", 500000, "MONTHLY", 5, 1, 100, 14, 500, 1, 1, 1, 0),
        (170, "ten_apex_170", "Apex Cabs & Logistics", "ENTERPRISE", "ACTIVE", 2500000, "ANNUAL", 25, 18, 1500, 1120, 425000, 1, 1, 1, 1),
        (171, "ten_bluestar_171", "BlueStar Mobility", "GROWTH", "SLA_PROBATION", 500000, "MONTHLY", 5, 2, 100, 42, 120000, 0, 1, 1, 0),
        (172, "ten_garuda_172", "Garuda City Fleets", "SOLO", "TRIAL", 0, "MONTHLY", 1, 1, 20, 19, 0, 0, 0, 1, 0),
        (173, "ten_royal_173", "Royal Executive Rentals", "GROWTH", "PAST_DUE", 500000, "MONTHLY", 5, 3, 100, 88, 25000, 1, 1, 0, 0),
        (174, "ten_metro_174", "Metro Commute Express", "GROWTH", "ACTIVE", 500000, "MONTHLY", 5, 2, 100, 60, 350000, 1, 1, 1, 1),
        (175, "ten_deccan_175", "Deccan Wheels Premium", "SOLO", "ACTIVE", 200000, "MONTHLY", 2, 1, 20, 12, 80000, 1, 1, 1, 0),
        (176, "ten_kaveri_176", "Kaveri Logistics & Tours", "GROWTH", "TRIAL", 0, "MONTHLY", 3, 1, 20, 5, 0, 0, 1, 1, 0),
    ]

    for v in vendors:
        end_iso = (now + dt.timedelta(days=30)).isoformat()
        conn.execute("""
        INSERT OR REPLACE INTO tenant_subscriptions (
            tenant_id, tenant_uuid, tenant_name, plan_tier, subscription_status, mrr_paise,
            billing_cycle, current_period_start, current_period_end, corporate_quota_total,
            corporate_quota_used, trip_quota_total, trip_quota_used, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (v[0], v[1], v[2], v[3], v[4], v[5], v[6], now_iso, end_iso, v[7], v[8], v[9], v[10], now_iso, now_iso))

        conn.execute("""
        INSERT OR REPLACE INTO tenant_wallets (tenant_id, balance_paise, currency, updated_at)
        VALUES (?, ?, 'INR', ?)
        """, (v[0], v[11], now_iso))

        conn.execute("""
        INSERT OR REPLACE INTO tenant_feature_flags (
            tenant_id, network_exchange_enabled, marketplace_enabled, parse_ai_intake_enabled,
            whatsapp_bot_enabled, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (v[0], v[12], v[13], v[14], v[15], now_iso))

    # 2. SEED 5 CORPORATE CLIENTS
    corporates = [
        ("corp_infosys_01", "Infosys BPM Ltd", "Bengaluru", "+91 80 2852 0261", "29AABCI1234F1Z1"),
        ("corp_wipro_02", "Wipro Technologies Ltd", "Bengaluru", "+91 80 2844 0011", "29AAACW5678H1Z2"),
        ("corp_deloitte_03", "Deloitte USI Solutions", "Bengaluru", "+91 80 6627 6000", "29AABCD9012K1Z3"),
        ("corp_target_04", "Target India Enterprise", "Bengaluru", "+91 80 4135 2000", "29AAACT3456L1Z4"),
        ("corp_accenture_05", "Accenture Operations GCC", "Bengaluru", "+91 80 4106 0000", "29AABCA7890M1Z5"),
    ]
    for c in corporates:
        conn.execute("""
        INSERT OR IGNORE INTO organizations (id, kind, name, city, phone, gstin, created_at)
        VALUES (?, 'corporate', ?, ?, ?, ?, ?)
        """, (c[0], c[1], c[2], c[3], c[4], now_iso))

    # 3. SEED 25 REALISTIC DUTIES
    has_domain_duties = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='domain_duties'").fetchone()[0]
    if has_domain_duties:
        cur_d = conn.execute("SELECT count(*) FROM domain_duties WHERE id LIKE 'DUTY_DEMO_%'")
        if cur_d.fetchone()[0] == 0:
            statuses = ["in_progress"] * 8 + ["completed"] * 11 + ["unallotted"] * 2 + ["audit_hold"] * 2 + ["auto_slab_upgraded"] * 2
            for i, st in enumerate(statuses, 1):
                d_id = f"DUTY_DEMO_{i:03d}"
                conn.execute("""
                INSERT OR IGNORE INTO domain_duties (
                    id, organization_id, booking_id, driver_id, vehicle_id, status,
                    reporting_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    d_id,
                    org_id,
                    f"BOOK_DEMO_{i:03d}",
                    f"drv_demo_{(i % 4) + 1}",
                    f"veh_demo_{(i % 4) + 1}",
                    st,
                    (now + dt.timedelta(hours=i)).isoformat(),
                    now_iso,
                    now_iso
                ))

    # 4. SEED 2 DISTANCE AUDIT HOLDS IN tristack_maker_checker_queue
    conn.execute("""
    INSERT OR REPLACE INTO tristack_maker_checker_queue (
        id, organization_id, duty_id, reason, odometer_delta_km, snapped_route_km,
        variance_pct, variance_km, status, created_at
    ) VALUES
        ('mc_task_8819', ?, 'DUTY_DEMO_022', 'Odometer variance +22.2% (>10% and >5km)', 88.0, 71.8, 22.2, 16.2, 'PENDING_REVIEW', ?),
        ('mc_task_8820', ?, 'DUTY_DEMO_023', 'Odometer variance +35.0% (>10% and >5km)', 95.0, 62.0, 35.0, 33.0, 'PENDING_REVIEW', ?)
    """, (org_id, now_iso, org_id, now_iso))

    # 5. SEED VERIFIED GUARDS IN tristack_security_guards
    conn.execute("""
    INSERT OR REPLACE INTO tristack_security_guards (
        id, organization_id, guard_name, badge_number, phone, agency_name, status, start_otp, end_otp, created_at
    ) VALUES
        ('guard_blr_001', ?, 'Rajesh Shinde', 'SEC-BLR-1092', '+91 98450 11999', 'SIS Security Services', 'ACTIVE', '445566', '778899', ?),
        ('guard_blr_002', ?, 'Mahesh Kumar', 'SEC-BLR-2041', '+91 98450 22888', 'G4S Fleet Escort', 'ACTIVE', '112233', '998877', ?)
    """, (org_id, now_iso, org_id, now_iso))

    # 6. SEED 15 WEBHOOK AUDIT LOGS IN tristack_webhook_logs (12 OK + 3 FAILED)
    conn.execute("DELETE FROM tristack_webhook_logs WHERE id LIKE 'wh_demo_%'")
    for i in range(1, 16):
        wh_id = f"wh_demo_{i:03d}"
        if i <= 12:
            status = 200
            err_msg = None
            is_dead = 0
            payload = {
                "duty_id": f"DUTY_DEMO_{i:03d}",
                "event": "DUTY_COMPLETED" if i % 2 == 0 else "TRIP_LOCATION_PING",
                "authorization": "***REDACTED***",
                "passenger_phone": f"+91 ***** **{i:02d}",
                "pickup_coords": {"lat": "***REDACTED***", "lng": "***REDACTED***"},
                "timestamp": now_iso
            }
            resp_payload = {"ok": True, "message": "Webhook processed successfully", "receipt_id": f"rcpt_{i}"}
        else:
            status = 500 if i == 13 else 429 if i == 14 else 504
            err_msg = "Gateway timeout: upstream partner did not respond in 3000ms" if status == 504 else "Rate limit exceeded" if status == 429 else "Internal server error"
            is_dead = 1
            payload = {
                "duty_id": f"DUTY_DEMO_{i:03d}",
                "event": "BILLING_PROFORMA_SUBMITTED",
                "authorization": "***REDACTED***",
                "timestamp": now_iso
            }
            resp_payload = {"ok": False, "error": err_msg}

        conn.execute("""
        INSERT INTO tristack_webhook_logs (
            id, organization_id, direction, service_name, endpoint_url, http_method,
            request_payload_json, response_payload_json, http_status, latency_ms,
            retry_count, is_dead_letter, error_message, created_at
        ) VALUES (?, ?, 'OUTBOUND', 'ClientIntegrationWebhook', 'https://api.corporate-mobility.com/v1/axiom-events', 'POST', ?, ?, ?, 142, 0, ?, ?, ?)
        """, (
            wh_id,
            org_id,
            json.dumps(payload),
            json.dumps(resp_payload),
            status,
            is_dead,
            err_msg,
            now_iso
        ))

    conn.commit()
    print("SUCCESS: Seeded 8 Vendors, 5 Corporates, 25 Duties, 2 Audit Holds, 2 Security Guards, and 15 Webhooks!")


if __name__ == "__main__":
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    seed_demo_data(c)
    c.close()
