-- 20261027100000_system_resilience_indexes.sql
-- System Resilience & Query Optimization Migration: Covering, Composite, and Foreign Key Indexes

DO $$
BEGIN
    -- 1. Bookings indexes
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'bookings') THEN
        CREATE INDEX IF NOT EXISTS idx_bookings_org_status_sched ON public.bookings (organization_id, status, scheduled_at);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_bookings') THEN
        CREATE INDEX IF NOT EXISTS idx_domain_bookings_org_status_sched ON public.domain_bookings (organization_id, status, scheduled_at);
    END IF;

    -- 2. Duties indexes
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'duties') THEN
        CREATE INDEX IF NOT EXISTS idx_duties_org_status_report ON public.duties (organization_id, status, reporting_at);
        CREATE INDEX IF NOT EXISTS idx_duties_driver ON public.duties (driver_id);
        CREATE INDEX IF NOT EXISTS idx_duties_vehicle ON public.duties (vehicle_id);
        CREATE INDEX IF NOT EXISTS idx_duties_booking ON public.duties (booking_id);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_duties') THEN
        CREATE INDEX IF NOT EXISTS idx_domain_duties_org_status_report ON public.domain_duties (organization_id, status, reporting_at);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_driver ON public.domain_duties (driver_id);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_vehicle ON public.domain_duties (vehicle_id);
        CREATE INDEX IF NOT EXISTS idx_domain_duties_booking ON public.domain_duties (booking_id);
    END IF;

    -- 3. Invoices indexes
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'invoices') THEN
        CREATE INDEX IF NOT EXISTS idx_invoices_org_status_cust ON public.invoices (organization_id, status, customer_id);
        CREATE INDEX IF NOT EXISTS idx_invoices_customer ON public.invoices (customer_id);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_invoices') THEN
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_org_status_duty ON public.domain_invoices (organization_id, status, duty_id);
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_duty ON public.domain_invoices (duty_id);
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_customer ON public.domain_invoices (customer_id);
        CREATE INDEX IF NOT EXISTS idx_domain_invoices_org_idempotency ON public.domain_invoices (organization_id, idempotency_key);
    END IF;

    -- 4. Drivers indexes
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'drivers') THEN
        CREATE INDEX IF NOT EXISTS idx_drivers_compliance ON public.drivers (organization_id, status, license_expires_at);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_drivers') THEN
        CREATE INDEX IF NOT EXISTS idx_domain_drivers_compliance ON public.domain_drivers (organization_id, status, license_expiry);
    END IF;

    -- 5. Vehicles indexes
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'vehicles') THEN
        CREATE INDEX IF NOT EXISTS idx_vehicles_compliance ON public.vehicles (organization_id, status, registration_number);
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'domain_vehicles') THEN
        CREATE INDEX IF NOT EXISTS idx_domain_vehicles_compliance ON public.domain_vehicles (organization_id, status, insurance_expiry);
    END IF;
END $$;
