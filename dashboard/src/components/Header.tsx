import React from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';

interface HeaderProps {
  title: string;
  subtitle: string;
  backendAlive: boolean;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  subtitle,
  backendAlive,
  onRefresh,
  isRefreshing,
}) => {
  return (
    <header style={{
      height: '64px',
      backgroundColor: '#ffffff',
      borderBottom: '1px solid #e2e8f0',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 28px',
      flexShrink: 0,
    }}>
      <div>
        <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: '#0f172a', letterSpacing: '-0.01em' }}>
          {title}
        </h1>
        <p style={{ margin: 0, fontSize: '12px', color: '#64748b' }}>
          {subtitle}
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        {/* Backend Status Indicator */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '7px',
          padding: '5px 12px',
          borderRadius: '999px',
          backgroundColor: backendAlive ? '#ecfdf5' : '#fef2f2',
          border: `1px solid ${backendAlive ? '#a7f3d0' : '#fecaca'}`,
          fontSize: '11.5px',
          fontWeight: 600,
          color: backendAlive ? '#047857' : '#b91c1c',
        }}>
          <span style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            backgroundColor: backendAlive ? '#10b981' : '#ef4444',
            display: 'inline-block',
          }} />
          {backendAlive ? 'FastAPI ASGI Online' : 'Backend Disconnected'}
        </div>

        {/* Refresh button */}
        <button
          onClick={onRefresh}
          disabled={isRefreshing}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 12px',
            borderRadius: '6px',
            border: '1px solid #cbd5e1',
            backgroundColor: '#ffffff',
            color: '#334155',
            fontSize: '12px',
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          <RefreshCw size={13} className={isRefreshing ? 'animate-spin' : ''} />
          <span>Sync</span>
        </button>

        {/* Link back to original Single Page App */}
        <a
          href="http://localhost:4173/#overview"
          target="_blank"
          rel="noreferrer"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 12px',
            borderRadius: '6px',
            backgroundColor: '#0f172a',
            color: '#ffffff',
            fontSize: '12px',
            fontWeight: 500,
            textDecoration: 'none',
          }}
        >
          <span>Legacy Console</span>
          <ExternalLink size={13} />
        </a>
      </div>
    </header>
  );
};
