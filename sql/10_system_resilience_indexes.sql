-- 10_system_resilience_indexes.sql
-- System Resilience & Query Optimization Migration: Covering, Composite, and Foreign Key Indexes

-- 1. High-Frequency State & Schedule Composite Indexes
CREATE INDEX IF NOT EXISTS idx_domain_bookings_org_status_sched 
    ON domain_bookings (organization_id, status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_domain_duties_org_status_report 
    ON domain_duties (organization_id, status, reporting_at);

CREATE INDEX IF NOT EXISTS idx_domain_invoices_org_status_duty 
    ON domain_invoices (organization_id, status, duty_id);

-- 2. Foreign Key Indexes for Operational Lookups & Join Acceleration
CREATE INDEX IF NOT EXISTS idx_domain_duties_driver 
    ON domain_duties (driver_id);

CREATE INDEX IF NOT EXISTS idx_domain_duties_vehicle 
    ON domain_duties (vehicle_id);

CREATE INDEX IF NOT EXISTS idx_domain_duties_booking 
    ON domain_duties (booking_id);

CREATE INDEX IF NOT EXISTS idx_domain_invoices_duty 
    ON domain_invoices (duty_id);

CREATE INDEX IF NOT EXISTS idx_domain_invoices_customer 
    ON domain_invoices (customer_id);

-- 3. Idempotency Key Index
CREATE INDEX IF NOT EXISTS idx_domain_invoices_org_idempotency 
    ON domain_invoices (organization_id, idempotency_key);

-- 4. Driver & Vehicle Compliance & Expiry Filter Indexes
CREATE INDEX IF NOT EXISTS idx_domain_drivers_compliance 
    ON domain_drivers (organization_id, status, license_expiry);

CREATE INDEX IF NOT EXISTS idx_domain_vehicles_compliance 
    ON domain_vehicles (organization_id, status, insurance_expiry);
