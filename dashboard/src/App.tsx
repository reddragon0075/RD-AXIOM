import { useState, useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { Header } from './components/Header';
import { Overview } from './pages/Overview';
import { Fleet } from './pages/Fleet';
import { LiveRadar } from './pages/LiveRadar';
import { api } from './api/client';
import type { Vehicle, Driver, Duty, TelemetryPing } from './api/client';

export function App() {
  const [currentTab, setCurrentTab] = useState('overview');
  const [backendAlive, setBackendAlive] = useState(false);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [duties, setDuties] = useState<Duty[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryPing[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchAll = async () => {
    setIsRefreshing(true);
    try {
      // 1. Health check
      const health = await api.getHealth().catch(() => ({ ok: false }));
      setBackendAlive(Boolean(health.ok));

      // 2. Core entities
      const [vRes, dRes, dutyRes, tRes] = await Promise.all([
        api.getVehicles(50).catch(() => ({ items: [] })),
        api.getDrivers(50).catch(() => ({ items: [] })),
        api.getDuties(50).catch(() => ({ items: [] })),
        api.getLiveTelemetry().catch(() => ({ drivers: [] })),
      ]);

      if (vRes.items) setVehicles(vRes.items);
      if (dRes.items) setDrivers(dRes.items);
      if (dutyRes.items) setDuties(dutyRes.items);
      if (tRes.drivers) setTelemetry(tRes.drivers);
    } catch (e) {
      console.warn('Dashboard sync warning:', e);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAll();
    // Background polling every 10 seconds
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, []);

  const getHeaderMeta = () => {
    switch (currentTab) {
      case 'overview':
        return { title: 'Executive Operations Overview', subtitle: 'Live fleet performance, telemetry, and duty dispatch metrics' };
      case 'fleet':
        return { title: 'Vehicle Registry & Assets', subtitle: 'Manage owned, attached, and partner vehicles across all city hubs' };
      case 'radar':
        return { title: 'Real-Time GPS Telemetry Radar', subtitle: 'Live high-frequency driver coordinates and WebSocket dispatch stream' };
      case 'drivers':
        return { title: 'Professional Chauffeurs Roster', subtitle: 'Verified drivers, compliance documents, and availability statuses' };
      case 'duties':
        return { title: 'Trip Dispatch & Lifecycle Board', subtitle: 'Active corporate bookings, OTP verification, and trip progress' };
      case 'tariffs':
        return { title: 'Corporate Rate Cards & Tariffs', subtitle: 'Multi-factor customer pricing, auto-slabs, and rate card waterfalls' };
      case 'invoices':
        return { title: 'Dual-Ledger Invoicing & P&L', subtitle: 'Corporate GST tax invoices, chauffeur payouts, and gross margins' };
      default:
        return { title: 'Axiom Fleet Enterprise', subtitle: 'High-Volume Mobility SaaS ERP' };
    }
  };

  const meta = getHeaderMeta();

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden', fontFamily: 'Inter, system-ui, -apple-system, sans-serif' }}>
      {/* Sleek Enterprise Sidebar */}
      <Sidebar
        currentTab={currentTab}
        onSelectTab={setCurrentTab}
        telemetryCount={telemetry.length}
      />

      {/* Main Content Area */}
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100vh', overflow: 'hidden' }}>
        <Header
          title={meta.title}
          subtitle={meta.subtitle}
          backendAlive={backendAlive}
          onRefresh={fetchAll}
          isRefreshing={isRefreshing}
        />

        {currentTab === 'overview' && (
          <Overview
            vehicles={vehicles}
            drivers={drivers}
            duties={duties}
            telemetry={telemetry}
            onSelectTab={setCurrentTab}
          />
        )}

        {currentTab === 'fleet' && (
          <Fleet
            vehicles={vehicles}
          />
        )}

        {currentTab === 'radar' && (
          <LiveRadar
            initialTelemetry={telemetry}
          />
        )}

        {['drivers', 'duties', 'customers', 'tariffs', 'invoices'].includes(currentTab) && (
          <div style={{ padding: '36px', backgroundColor: '#f8fafc', flex: 1, overflowY: 'auto' }}>
            <div style={{
              backgroundColor: '#ffffff',
              borderRadius: '10px',
              padding: '32px',
              border: '1px solid #e2e8f0',
              textAlign: 'center',
              maxWidth: '680px',
              margin: '20px auto',
            }}>
              <h3 style={{ margin: '0 0 10px 0', fontSize: '18px', color: '#0f172a' }}>
                {meta.title} Module Scaffolding
              </h3>
              <p style={{ margin: '0 0 20px 0', fontSize: '13px', color: '#64748b', lineHeight: 1.5 }}>
                This enterprise module is wired to your FastAPI backend API. You can view all live data right now or use the legacy console.
              </p>
              <div style={{ display: 'flex', justifyContent: 'center', gap: '12px' }}>
                <a
                  href={`http://localhost:4173/#${currentTab}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{
                    display: 'inline-block',
                    padding: '8px 16px',
                    borderRadius: '6px',
                    backgroundColor: '#2563eb',
                    color: '#ffffff',
                    fontSize: '12.5px',
                    fontWeight: 600,
                    textDecoration: 'none',
                  }}
                >
                  Open in Legacy Console &rarr;
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default App;
