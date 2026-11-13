/**
 * Axiom Fleet Enterprise API Client
 * Connects directly to the FastAPI/ASGI backend with typed responses.
 */

export interface ApiResponse<T = any> {
  ok: boolean;
  item?: T;
  items?: T[];
  count?: number;
  error?: string;
  message?: string;
  status?: string;
}

export interface Vehicle {
  id: string;
  registration_number: string;
  make_model: string;
  vehicle_group: string;
  vehicle_type?: string;
  fuel_type?: string;
  city?: string;
  current_odometer_km?: number;
  status: string;
}

export interface Driver {
  id: string;
  full_name: string;
  phone: string;
  city?: string;
  vehicle_group?: string;
  license_number?: string;
  badge_number?: string;
  status: string;
}

export interface Duty {
  id: string;
  booking_id: string;
  trip_id?: string;
  status: string;
  vehicle_id?: string;
  driver_id?: string;
  passenger_name?: string;
  duty_type?: string;
  reporting_at?: string;
}

export interface TelemetryPing {
  driver_id: string;
  duty_id?: string;
  lat: number;
  lng: number;
  speed_kmh?: number;
  heading?: number;
  timestamp?: string;
}

const DEFAULT_HEADERS: HeadersInit = {
  'Content-Type': 'application/json',
  'X-Axiom-User-Email': 'reddragon0075@gmail.com',
};

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = endpoint.startsWith('http') ? endpoint : endpoint;
  const res = await fetch(url, {
    ...options,
    headers: {
      ...DEFAULT_HEADERS,
      ...options.headers,
    },
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(errorBody.message || errorBody.error || `HTTP ${res.status}`);
  }

  return res.json();
}

export const api = {
  // Health
  getHealth: () => request<{ ok: boolean; status: string; server: string }>('/health/live'),

  // Telemetry
  getLiveTelemetry: () =>
    request<{ ok: boolean; count: number; drivers: TelemetryPing[]; time: string }>('/api/telemetry/live'),

  // Fleets & Masters
  getVehicles: (limit = 50) => request<ApiResponse<Vehicle>>(`/api/vehicles?limit=${limit}`),
  getDrivers: (limit = 50) => request<ApiResponse<Driver>>(`/api/drivers?limit=${limit}`),
  getCustomers: (limit = 50) => request<ApiResponse<any>>(`/api/customers?limit=${limit}`),
  getCustomer360: (id: string) => request<any>(`/api/customers/${encodeURIComponent(id)}/360`),

  // Operations
  getDuties: (limit = 50) => request<ApiResponse<Duty>>(`/api/duties?limit=${limit}`),
  getBookings: (limit = 50) => request<ApiResponse<any>>(`/api/bookings?limit=${limit}`),
  getInvoices: (limit = 50) => request<ApiResponse<any>>(`/api/invoices?limit=${limit}`),

  // Tariff & Pricing
  getTariffRules: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<ApiResponse<any>>(`/api/fare/rules${qs}`);
  },
  calculateFare: (payload: any) =>
    request<any>('/api/fare/calculate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

