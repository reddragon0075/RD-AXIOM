import React from 'react';
import {
  LayoutDashboard,
  Radio,
  Car,
  Users,
  Building2,
  Receipt,
  Settings,
  ShieldCheck,
  ChevronRight,
  TrendingUp,
} from 'lucide-react';

interface SidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  telemetryCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentTab, onSelectTab, telemetryCount = 0 }) => {
  const navSections = [
    {
      title: 'Operations',
      items: [
        { id: 'overview', label: 'Overview', icon: LayoutDashboard },
        { id: 'radar', label: 'Live GPS Radar', icon: Radio, badge: telemetryCount > 0 ? `${telemetryCount} live` : undefined },
        { id: 'duties', label: 'Dispatch & Duties', icon: TrendingUp },
      ],
    },
    {
      title: 'Fleet & Masters',
      items: [
        { id: 'fleet', label: 'Vehicles Registry', icon: Car },
        { id: 'drivers', label: 'Chauffeurs Roster', icon: Users },
        { id: 'customers', label: 'Corporate Accounts', icon: Building2 },
      ],
    },
    {
      title: 'Finance & Tariffs',
      items: [
        { id: 'tariffs', label: 'Corporate Rate Cards', icon: Settings },
        { id: 'invoices', label: 'Dual-Ledger Invoicing', icon: Receipt },
      ],
    },
  ];

  return (
    <aside style={{
      width: '260px',
      height: '100vh',
      backgroundColor: '#090d16',
      color: '#f8fafc',
      display: 'flex',
      flexDirection: 'column',
      borderRight: '1px solid rgba(255, 255, 255, 0.08)',
      userSelect: 'none',
      flexShrink: 0,
    }}>
      {/* Brand Header */}
      <div style={{
        padding: '20px 18px',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
      }}>
        <div style={{
          width: '36px',
          height: '36px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, #2563eb, #38bdf8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 0 16px rgba(37, 99, 235, 0.4)',
        }}>
          <ShieldCheck size={20} color="#ffffff" />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: '15px', letterSpacing: '-0.01em', color: '#ffffff' }}>
            AXIOM FLEET
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981', display: 'inline-block' }} />
            FastAPI ASGI · 2.0
          </div>
        </div>
      </div>

      {/* Navigation Sections */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 12px' }}>
        {navSections.map((sec, idx) => (
          <div key={idx} style={{ marginBottom: '22px' }}>
            <div style={{
              fontSize: '10.5px',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: '#64748b',
              padding: '0 8px 8px',
            }}>
              {sec.title}
            </div>
            {sec.items.map((item) => {
              const Icon = item.icon;
              const isActive = currentTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onSelectTab(item.id)}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '9px 12px',
                    borderRadius: '7px',
                    border: 'none',
                    background: isActive ? 'rgba(37, 99, 235, 0.15)' : 'transparent',
                    color: isActive ? '#60a5fa' : '#cbd5e1',
                    cursor: 'pointer',
                    fontSize: '13px',
                    fontWeight: isActive ? 600 : 500,
                    marginBottom: '3px',
                    transition: 'all 0.15s ease',
                    textAlign: 'left',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Icon size={16} color={isActive ? '#60a5fa' : '#94a3b8'} />
                    <span>{item.label}</span>
                  </div>
                  {item.badge ? (
                    <span style={{
                      fontSize: '10px',
                      padding: '2px 7px',
                      borderRadius: '999px',
                      backgroundColor: '#ef4444',
                      color: '#ffffff',
                      fontWeight: 600,
                    }}>
                      {item.badge}
                    </span>
                  ) : isActive ? (
                    <ChevronRight size={14} color="#60a5fa" />
                  ) : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* User / Organization Footer */}
      <div style={{
        padding: '14px 16px',
        borderTop: '1px solid rgba(255, 255, 255, 0.06)',
        backgroundColor: 'rgba(0, 0, 0, 0.25)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '30px',
            height: '30px',
            borderRadius: '50%',
            backgroundColor: '#3b82f6',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 700,
            fontSize: '12px',
          }}>
            A
          </div>
          <div>
            <div style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>Abhijith</div>
            <div style={{ fontSize: '10px', color: '#64748b' }}>Axiom Logistics</div>
          </div>
        </div>
      </div>
    </aside>
  );
};

