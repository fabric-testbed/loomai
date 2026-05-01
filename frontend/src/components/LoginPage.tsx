'use client';
import React, { useState, FormEvent } from 'react';
import { assetUrl } from '../utils/assetUrl';

interface LoginPageProps {
  onSuccess: () => void;
}

const BASE = (typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH)
  ? `${window.__LOOMAI_BASE_PATH}/api`
  : '/api';

export default function LoginPage({ onSuccess }: LoginPageProps) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (res.ok) {
        onSuccess();
      } else {
        setError('Invalid password');
      }
    } catch {
      setError('Connection failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(135deg, #1a1d23 0%, #2d3748 100%)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      <form onSubmit={handleSubmit} style={{
        background: '#2d3748',
        borderRadius: 12,
        padding: '40px 36px',
        width: 360,
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 20,
      }}>
        {/* LoomAI horizontal logo (on-dark variant) */}
        <svg width="260" height="80" viewBox="0 0 480 120" xmlns="http://www.w3.org/2000/svg" style={{ marginBottom: 4 }}>
          <rect x="16" y="16" width="88" height="88" rx="14" fill="#1c2e4a"/>
          <rect x="45.5" y="25.7" width="29.1" height="18.3" rx="4.0" fill="#27aae1"/>
          <rect x="25.7" y="50.9" width="68.6" height="18.3" rx="4.0" fill="#27aae1"/>
          <rect x="45.5" y="76.1" width="29.1" height="18.3" rx="4.0" fill="#27aae1"/>
          <rect x="25.7" y="25.7" width="18.3" height="23.7" rx="4.0" fill="#4cc4f0"/>
          <rect x="25.7" y="70.7" width="18.3" height="23.6" rx="4.0" fill="#4cc4f0"/>
          <rect x="50.9" y="45.5" width="18.3" height="29.1" rx="4.0" fill="#4cc4f0"/>
          <rect x="76.1" y="25.7" width="18.3" height="23.7" rx="4.0" fill="#4cc4f0"/>
          <rect x="76.1" y="70.7" width="18.3" height="23.6" rx="4.0" fill="#4cc4f0"/>
          <circle cx="60.0" cy="60.0" r="4.4" fill="#e8f0f8"/>
          <line x1="118" y1="20" x2="118" y2="100" stroke="#27aae1" strokeWidth="1.5" opacity="0.3"/>
          <text x="134" y="72" fontSize="46" fontWeight="700" letterSpacing="-1.5" fill="#ffffff" fontFamily="'Inter','Helvetica Neue',Arial,sans-serif">Loom<tspan fill="#27aae1">AI</tspan></text>
          <text x="136" y="91" fontSize="9.5" letterSpacing="3" fill="#7aaac8" fontFamily="'Inter','Helvetica Neue',Arial,sans-serif">WEAVE · BUILD · DISCOVER</text>
        </svg>
        <p style={{
          margin: 0,
          fontSize: 13,
          color: '#a0aec0',
          textAlign: 'center',
        }}>
          Enter the password shown in the container logs
        </p>
        {/* POWERED BY FABRIC */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, opacity: 0.7 }}>
          <span style={{ fontSize: 11, color: '#a0aec0', letterSpacing: 1 }}>POWERED BY</span>
          <img
            src={assetUrl('/fabric_logo_light.png')}
            alt="FABRIC"
            style={{ height: 28 }}
            onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
          />
        </div>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Password"
          autoFocus
          style={{
            width: '100%',
            padding: '10px 14px',
            borderRadius: 8,
            border: '1px solid #4a5568',
            background: '#1a202c',
            color: '#e2e8f0',
            fontSize: 15,
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
        {error && (
          <div style={{ color: '#fc8181', fontSize: 13, margin: '-8px 0 0' }}>
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={loading || !password}
          style={{
            width: '100%',
            padding: '10px 0',
            borderRadius: 8,
            border: 'none',
            background: loading || !password ? '#4a5568' : 'linear-gradient(135deg, #27aae1, #0e7ab5)',
            color: '#fff',
            fontSize: 15,
            fontWeight: 600,
            cursor: loading || !password ? 'default' : 'pointer',
            transition: 'opacity 0.15s',
          }}
        >
          {loading ? 'Signing in...' : 'Sign In'}
        </button>
      </form>
    </div>
  );
}
