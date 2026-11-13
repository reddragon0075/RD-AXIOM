import React, { useState, useEffect } from 'react';
import { Radio, Navigation, Send, Clock, Zap } from 'lucide-react';
import type { TelemetryPing } from '../api/client';

interface LiveRadarProps {
  initialTelemetry: TelemetryPing[];
}

export const LiveRadar: React.FC<LiveRadarProps> = ({ initialTelemetry }) => {
  const [telemetryList, setTelemetryList] = useState<TelemetryPing[]>(initialTelemetry);
  const [wsConnected, setWsConnected] = useState(false);
  const [testDriverId, setTestDriverId] = useState('drv_radar_demo');
  const [testLat, setTestLat] = useState('12.9716');
  const [testLng, setTestLng] = useState('77.5946');
  const [testSpeed, setTestSpeed] = useState('48.5');

  useEffect(() => {
    // Connect to FastAPI WebSocket Telemetry Stream
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;
    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      setWsConnected(true);
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'driver_telemetry' && data.telemetry) {
          setTelemetryList((prev) => {
            const filtered = prev.filter((d) => d.driver_id !== data.telemetry.driver_id);
            return [data.telemetry, ...filtered];
          });
        }
      } catch (err) {
        console.warn('WS message error:', err);
      }
    };

    socket.onclose = () => {
      setWsConnected(false);
    };

    return () => {
      socket.close();
    };
  }, []);

  const handleSendPing = async () => {
    const payload = {
      driver_id: testDriverId,
      lat: parseFloat(testLat),
      lng: parseFloat(testLng),
      speed_kmh: parseFloat(testSpeed),
      heading: 90,
      timestamp: new Date().toISOString(),
    };

    try {
      const res = await fetch('/api/telemetry/ping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setTelemetryList((prev) => {
          const filtered = prev.filter((d) => d.driver_id !== payload.driver_id);
          return [payload, ...filtered];
        });
      }
    } catch (e) {
      console.error('Failed to post telemetry ping:', e);
    }
  };

  return (
    <div style={{ padding: '24px 28px', backgroundColor: '#f8fafc', flex: 1, overflowY: 'auto' }}>
      {/* Top Banner */}
      <div style={{
        backgroundColor: '#ffffff',
        borderRadius: '10px',
        padding: '18px 22px',
        border: '1px solid #e2e8f0',
        marginBottom: '20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            backgroundColor: wsConnected ? '#ecfdf5' : '#fef2f2',
            color: wsConnected ? '#10b981' : '#ef4444',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <Radio size={22} className={wsConnected ? 'animate-pulse' : ''} />
          </div>
          <div>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: '#0f172a' }}>
              Real-Time Driver Telemetry Bus
            </h3>
            <p style={{ margin: 0, fontSize: '12px', color: '#64748b' }}>
              Connected to <code>ws://localhost:4173/ws/telemetry</code> · High-frequency GPS tracking stream
            </p>
          </div>
        </div>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 14px',
          borderRadius: '999px',
          backgroundColor: wsConnected ? '#ecfdf5' : '#fff1f2',
          border: `1px solid ${wsConnected ? '#a7f3d0' : '#fecdd3'}`,
          fontSize: '12px',
          fontWeight: 600,
          color: wsConnected ? '#059669' : '#e11d48',
        }}>
          <span style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: wsConnected ? '#10b981' : '#f43f5e',
          }} />
          {wsConnected ? 'WebSocket Channel Active' : 'Connecting to Stream...'}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: '22px' }}>
        {/* Left: Active Vehicles Grid */}
        <div style={{
          backgroundColor: '#ffffff',
          borderRadius: '10px',
          padding: '20px',
          border: '1px solid #e2e8f0',
        }}>
          <h4 style={{ margin: '0 0 14px 0', fontSize: '14px', fontWeight: 700, color: '#0f172a' }}>
            Live Broadcasting Drivers ({telemetryList.length})
          </h4>

          {telemetryList.length === 0 ? (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: '#94a3b8', fontSize: '13px' }}>
              No active vehicle GPS pings currently in memory.
              <br />
              <span style={{ fontSize: '11.5px', color: '#cbd5e1' }}>
                Use the simulator on the right or launch the Driver Cockpit at <code>/driver-app/</code>.
              </span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {telemetryList.map((t, idx) => (
                <div key={idx} style={{
                  padding: '14px 16px',
                  borderRadius: '8px',
                  backgroundColor: '#f8fafc',
                  border: '1px solid #e2e8f0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                      width: '34px',
                      height: '34px',
                      borderRadius: '8px',
                      backgroundColor: '#eff6ff',
                      color: '#2563eb',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}>
                      <Navigation size={18} />
                    </div>
                    <div>
                      <div style={{ fontSize: '13.5px', fontWeight: 700, color: '#0f172a' }}>{t.driver_id}</div>
                      <div style={{ fontSize: '11px', color: '#64748b' }}>
                        Lat: {t.lat.toFixed(5)} · Lng: {t.lng.toFixed(5)}
                      </div>
                    </div>
                  </div>

                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '14px', fontWeight: 800, color: '#059669' }}>
                      {t.speed_kmh?.toFixed(1) || '0.0'} km/h
                    </div>
                    <div style={{ fontSize: '10.5px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end' }}>
                      <Clock size={11} />
                      {t.timestamp ? new Date(t.timestamp).toLocaleTimeString() : 'Live'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: GPS Ping Simulator */}
        <div style={{
          backgroundColor: '#ffffff',
          borderRadius: '10px',
          padding: '20px',
          border: '1px solid #e2e8f0',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
            <Zap size={16} color="#3b82f6" />
            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 700, color: '#0f172a' }}>
              Telemetry Simulator
            </h4>
          </div>
          <p style={{ margin: '0 0 16px 0', fontSize: '12px', color: '#64748b' }}>
            Simulate an active driver cockpit sending live GPS coordinates.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <label style={{ fontSize: '11.5px', fontWeight: 600, color: '#475569', display: 'block', marginBottom: '4px' }}>Driver ID</label>
              <input
                type="text"
                value={testDriverId}
                onChange={(e) => setTestDriverId(e.target.value)}
                style={{ width: '100%', padding: '7px 10px', fontSize: '12.5px', borderRadius: '6px', border: '1px solid #cbd5e1', boxSizing: 'border-box' }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              <div>
                <label style={{ fontSize: '11.5px', fontWeight: 600, color: '#475569', display: 'block', marginBottom: '4px' }}>Latitude</label>
                <input
                  type="text"
                  value={testLat}
                  onChange={(e) => setTestLat(e.target.value)}
                  style={{ width: '100%', padding: '7px 10px', fontSize: '12.5px', borderRadius: '6px', border: '1px solid #cbd5e1', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ fontSize: '11.5px', fontWeight: 600, color: '#475569', display: 'block', marginBottom: '4px' }}>Longitude</label>
                <input
                  type="text"
                  value={testLng}
                  onChange={(e) => setTestLng(e.target.value)}
                  style={{ width: '100%', padding: '7px 10px', fontSize: '12.5px', borderRadius: '6px', border: '1px solid #cbd5e1', boxSizing: 'border-box' }}
                />
              </div>
            </div>

            <div>
              <label style={{ fontSize: '11.5px', fontWeight: 600, color: '#475569', display: 'block', marginBottom: '4px' }}>Speed (km/h)</label>
              <input
                type="text"
                value={testSpeed}
                onChange={(e) => setTestSpeed(e.target.value)}
                style={{ width: '100%', padding: '7px 10px', fontSize: '12.5px', borderRadius: '6px', border: '1px solid #cbd5e1', boxSizing: 'border-box' }}
              />
            </div>

            <button
              onClick={handleSendPing}
              style={{
                marginTop: '8px',
                padding: '9px 16px',
                borderRadius: '6px',
                border: 'none',
                backgroundColor: '#2563eb',
                color: '#ffffff',
                fontWeight: 600,
                fontSize: '12.5px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
              }}
            >
              <Send size={14} />
              <span>Broadcast GPS Ping</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
