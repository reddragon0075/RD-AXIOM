import React, { useState } from 'react';
import { Search, Gauge, Fuel } from 'lucide-react';
import type { Vehicle } from '../api/client';

interface FleetProps {
  vehicles: Vehicle[];
}

export const Fleet: React.FC<FleetProps> = ({ vehicles }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [groupFilter, setGroupFilter] = useState('ALL');

  const filtered = vehicles.filter((v) => {
    const matchesSearch =
      v.registration_number.toLowerCase().includes(searchTerm.toLowerCase()) ||
      v.make_model.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesGroup =
      groupFilter === 'ALL' ||
      v.vehicle_group?.toUpperCase() === groupFilter.toUpperCase();
    return matchesSearch && matchesGroup;
  });

  return (
    <div style={{ padding: '24px 28px', backgroundColor: '#f8fafc', flex: 1, overflowY: 'auto' }}>
      {/* Controls Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '20px',
        flexWrap: 'wrap',
        gap: '12px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: '#ffffff',
            border: '1px solid #cbd5e1',
            borderRadius: '6px',
            padding: '7px 12px',
            width: '280px',
          }}>
            <Search size={15} color="#94a3b8" style={{ marginRight: '8px' }} />
            <input
              type="text"
              placeholder="Search registration, model..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{
                border: 'none',
                outline: 'none',
                width: '100%',
                fontSize: '12.5px',
                color: '#0f172a',
              }}
            />
          </div>

          <select
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
            style={{
              padding: '7px 12px',
              borderRadius: '6px',
              border: '1px solid #cbd5e1',
              backgroundColor: '#ffffff',
              fontSize: '12.5px',
              color: '#334155',
              cursor: 'pointer',
            }}
          >
            <option value="ALL">All Vehicle Groups</option>
            <option value="SEDAN">Standard Sedan</option>
            <option value="PREMIUM_SUV">Premium SUV</option>
            <option value="SUV">SUV</option>
            <option value="EXECUTIVE_SEDAN">Executive Sedan</option>
          </select>
        </div>

        <div style={{ fontSize: '13px', color: '#64748b' }}>
          Showing <strong>{filtered.length}</strong> of {vehicles.length} vehicles
        </div>
      </div>

      {/* High-Performance Virtualized-Ready Table */}
      <div style={{
        backgroundColor: '#ffffff',
        borderRadius: '10px',
        border: '1px solid #e2e8f0',
        overflow: 'hidden',
        boxShadow: '0 1px 3px rgba(0,0,0,0.02)',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
              <th style={{ padding: '12px 16px', fontSize: '11.5px', fontWeight: 600, color: '#475569' }}>REGISTRATION</th>
              <th style={{ padding: '12px 16px', fontSize: '11.5px', fontWeight: 600, color: '#475569' }}>MAKE & MODEL</th>
              <th style={{ padding: '12px 16px', fontSize: '11.5px', fontWeight: 600, color: '#475569' }}>GROUP</th>
              <th style={{ padding: '12px 16px', fontSize: '11.5px', fontWeight: 600, color: '#475569' }}>ODOMETER</th>
              <th style={{ padding: '12px 16px', fontSize: '11.5px', fontWeight: 600, color: '#475569' }}>FUEL</th>
              <th style={{ padding: '12px 16px', fontSize: '11.5px', fontWeight: 600, color: '#475569' }}>STATUS</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((v) => (
              <tr
                key={v.id}
                style={{
                  borderBottom: '1px solid #f1f5f9',
                  transition: 'background 0.1s',
                }}
              >
                <td style={{ padding: '13px 16px', fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>
                  {v.registration_number}
                </td>
                <td style={{ padding: '13px 16px', fontSize: '13px', color: '#334155' }}>
                  {v.make_model}
                </td>
                <td style={{ padding: '13px 16px', fontSize: '12px', color: '#64748b' }}>
                  <span style={{
                    padding: '3px 8px',
                    borderRadius: '4px',
                    backgroundColor: '#f1f5f9',
                    fontWeight: 500,
                  }}>
                    {v.vehicle_group}
                  </span>
                </td>
                <td style={{ padding: '13px 16px', fontSize: '12.5px', color: '#334155' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Gauge size={13} color="#94a3b8" />
                    <span>{v.current_odometer_km ? `${v.current_odometer_km.toLocaleString()} km` : '—'}</span>
                  </div>
                </td>
                <td style={{ padding: '13px 16px', fontSize: '12px', color: '#64748b' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Fuel size={13} color="#94a3b8" />
                    <span>{v.fuel_type || 'Diesel'}</span>
                  </div>
                </td>
                <td style={{ padding: '13px 16px' }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '3px 9px',
                    borderRadius: '999px',
                    fontSize: '11px',
                    fontWeight: 600,
                    backgroundColor: v.status === 'available' ? '#ecfdf5' : '#f1f5f9',
                    color: v.status === 'available' ? '#047857' : '#64748b',
                    border: `1px solid ${v.status === 'available' ? '#a7f3d0' : '#e2e8f0'}`,
                  }}>
                    {v.status.toUpperCase()}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
