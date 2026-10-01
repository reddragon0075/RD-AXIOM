export type DutyStatus = 'draft' | 'assigned' | 'accepted' | 'en_route' | 'started' | 'paused' | 'completed';

export type Duty = {
  id: string;
  status: DutyStatus;
  reporting_at?: string | null;
  customer?: string;
  passenger?: string;
  pickup?: string;
  dropoff?: string;
  vehicle?: string;
  driver?: string;
  booking_id?: string;
  driver_id?: string | null;
  vehicle_id?: string | null;
  duty_type?: string;
  booking_reference?: string;
  calculation_snapshot?: { total_paise?: number };
};

export type QueueOperation = {
  entity_type: string;
  entity_id: string;
  operation: string;
  payload: Record<string, unknown>;
  idempotency_key: string;
  created_at: string;
};

export type MobileHome = {
  summary?: { open_duties?: number; in_progress?: number; open_alerts?: number; stale_locations?: number };
  next_duty?: Duty | null;
  duties?: Duty[];
  alerts?: Array<{ id?: string; alert_type?: string; severity?: string; title?: string; status?: string }>;
  updated_at?: string;
};

export type SessionUser = {
  id: string;
  email: string;
  role: string;
  full_name: string;
  phone?: string;
  profile?: { city?: string; timezone?: string; license_number?: string };
};

/** Read-only native contract for Phase 3 field context. Mutations remain in the web/operator boundary. */
export type Phase3PredictiveAlert = {
  id: string;
  entity_type: string;
  entity_id: string;
  alert_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  risk_score: number;
  confidence: number;
  lead_time_minutes: number;
  model_version: string;
  factors: Array<{ code: string; weight?: number; value?: unknown; unit?: string; explanation?: string }>;
  source_event_ids: string[];
  status: 'open' | 'acknowledged' | 'resolved' | 'suppressed';
  recommended_action?: string;
};

export type Phase3SustainabilitySummary = {
  trips: number;
  total_distance_km: number;
  total_emissions_kg: number;
  average_emissions_kg: number;
  electric_distance_share_pct: number;
  factor_version: string;
};

export type ApiResponse<T> = {
  ok: boolean;
  items?: T[];
  user?: SessionUser;
  access_token?: string;
  [key: string]: unknown;
};
