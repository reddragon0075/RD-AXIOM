import React from 'react';
import { Car, Users, TrendingUp, Radio, ArrowUpRight } from 'lucide-react';
import type { Vehicle, Driver, Duty, TelemetryPing } from '../api/client';

interface OverviewProps {
  vehicles: Vehicle[];
  drivers: Driver[];
  duties: Duty[];
  telemetry: TelemetryPing[];
  onSelectTab: (tab: string) => void;
}

export const Overview: React.FC<OverviewProps> = ({
  vehicles,
  drivers,
  duties,
  telemetry,
  onSelectTab,
}) => {
  const kpiCards = [
    {
      label: 'Executive Fleet',
      value: vehicles.length,
      unit: 'Vehicles Active',
      icon: Car,
      color: '#3b82f6',
      bg: '#eff6ff',
      tab: 'fleet',
    },
    {
      label: 'Professional Chauffeurs',
      value: drivers.length,
      unit: 'Drivers Onboarded',
      icon: Users,
      color: '#10b981',
      bg: '#ecfdf5',
      tab: 'drivers',
    },
    {
      label: 'Corporate Duties',
      value: duties.length,
      unit: 'Trips Dispatched',
      icon: TrendingUp,
      color: '#8b5cf6',
      bg: '#f5f3ff',
      tab: 'duties',
    },
    {
      label: 'Live GPS Telemetry',
      value: telemetry.length,
      unit: 'Broadcasting Drivers',
      icon: Radio,
      color: '#f59e0b',
      bg: '#fffbeb',
      tab: 'radar',
    },
  ];

  return (
    <div style={{ padding: '24px 28px', backgroundColor: '#f8fafc', flex: 1, overflowY: 'auto' }}>
      {/* KPI Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: '18px',
        marginBottom: '28px',
      }}>
        {kpiCards.map((c, i) => {
          const Icon = c.icon;
          return (
            <div
              key={i}
              onClick={() => onSelectTab(c.tab)}
              style={{
                backgroundColor: '#ffffff',
                borderRadius: '10px',
                padding: '20px',
                border: '1px solid #e2e8f0',
                boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                cursor: 'pointer',
                transition: 'transform 0.1s ease',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#64748b' }}>{c.label}</span>
                <div style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '8px',
                  backgroundColor: c.bg,
                  color: c.color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  <Icon size={18} />
                </div>
              </div>
              <div style={{ fontSize: '26px', fontWeight: 800, color: '#0f172a', lineHeight: 1.1 }}>
                {c.value}
              </div>
              <div style={{ fontSize: '11.5px', color: '#94a3b8', marginTop: '4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>{c.unit}</span>
                <ArrowUpRight size={14} color="#64748b" />
              </div>
            </div>
          );
        })}
      </div>

      {/* Main Split Section: Live Telemetry & Recent Fleets */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '22px' }}>
        {/* Left: Active Telemetry Drivers */}
        <div style={{
          backgroundColor: '#ffffff',
          borderRadius: '10px',
          padding: '20px',
          border: '1px solid #e2e8f0',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: '#0f172a' }}>Live GPS Telemetry Stream</h3>
              <p style={{ margin: 0, fontSize: '12px', color: '#64748b' }}>Real-time driver location updates via WebSocket (/ws/telemetry)</p>
            </div>
            <button
              onClick={() => onSelectTab('radar')}
              style={{
                fontSize: '11.5px',
                color: '#2563eb',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              Open Radar &rarr;
            </button>
          </div>

          {telemetry.length === 0 ? (
            <div style={{ padding: '36px', textAlign: 'center', color: '#94a3b8', fontSize: '13px' }}>
              No drivers broadcasting GPS coordinates right now.
              <div style={{ marginTop: '6px', fontSize: '11.5px', color: '#cbd5e1' }}>
                Open the Driver Cockpit App at <a href="http://localhost:4173/driver-app/" target="_blank" rel="noreferrer" style={{ color: '#3b82f6' }}>/driver-app/</a> to broadcast live GPS telemetry.
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {telemetry.map((t, idx) => (
                <div key={idx} style={{
                  padding: '12px 14px',
                  borderRadius: '8px',
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#10b981' }} />
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 600, color: '#1e293b' }}>{t.driver_id}</div>
                      <div style={{ fontSize: '11px', color: '#64748b' }}>Duty: {t.duty_id || 'Free Roam'}</div>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#0f172a' }}>{t.speed_kmh?.toFixed(1) || '0.0'} km/h</div>
                    <div style={{ fontSize: '10.5px', color: '#94a3b8' }}>{t.lat.toFixed(4)}, {t.lng.toFixed(4)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Executive Fleet Highlights */}
        <div style={{
          backgroundColor: '#ffffff',
          borderRadius: '10px',
          padding: '20px',
          border: '1px solid #e2e8f0',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: '#0f172a' }}>Registered Fleet</h3>
              <p style={{ margin: 0, fontSize: '12px', color: '#64748b' }}>Executive Sedans & Premium SUVs</p>
            </div>
            <button
              onClick={() => onSelectTab('fleet')}
              style={{
                fontSize: '11.5px',
                color: '#2563eb',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              View All ({vehicles.length}) &rarr;
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {vehicles.slice(0, 5).map((v) => (
              <div key={v.id} style={{
                padding: '12px 14px',
                borderRadius: '8px',
                backgroundColor: '#ffffff',
                border: '1px solid #f1f5f9',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>{v.registration_number}</div>
                  <div style={{ fontSize: '11px', color: '#64748b' }}>{v.make_model} · {v.vehicle_group}</div>
                </div>
                <span style={{
                  fontSize: '10.5px',
                  fontWeight: 600,
                  padding: '3px 8px',
                  borderRadius: '999px',
                  backgroundColor: v.status === 'available' ? '#ecfdf5' : '#f1f5f9',
                  color: v.status === 'available' ? '#059669' : '#64748b',
                }}>
                  {v.status.toUpperCase()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
