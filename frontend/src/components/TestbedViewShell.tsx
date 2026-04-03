'use client';
import React from 'react';
import '../styles/testbed-view.css';

/* ── Theme definitions ─────────────────────────────────────────── */

export interface TestbedTheme {
  name: string;           // "FABRIC" or "Chameleon"
  primary: string;        // brand primary color
  dark: string;           // darker variant
  light: string;          // light tint
  logo: string;           // path to logo image (light mode)
  logoDark?: string;      // path to logo image (dark mode, optional)
  logoAlt: string;        // alt text
}

export const FABRIC_THEME: TestbedTheme = {
  name: 'FABRIC',
  primary: '#5798bc',
  dark: '#1f6a8c',
  light: '#e8f4f8',
  logo: '/fabric_wave_dark.png',
  logoDark: '/fabric_wave_light.png',
  logoAlt: 'FABRIC Testbed',
};

export const CHAMELEON_THEME: TestbedTheme = {
  name: 'Chameleon',
  primary: '#39B54A',
  dark: '#2d8f3a',
  light: '#e8f8ea',
  logo: '/chameleon-icon.png',
  logoAlt: 'Chameleon Cloud',
};

export const COMPOSITE_THEME: TestbedTheme = {
  name: 'Composite Slices',
  primary: '#27aae1',
  dark: '#1c2e4a',
  light: '#e8f4fc',
  logo: '/composite-slice-icon-transparent.svg',
  logoAlt: 'Composite Slices',
};

/* ── Tab definition ────────────────────────────────────────────── */

export interface Tab {
  id: string;
  label: string;
  badge?: number;
}

/* ── Shell Props ───────────────────────────────────────────────── */

interface TestbedViewShellProps {
  theme: TestbedTheme;
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  toolbarContent?: React.ReactNode;   // slice/lease selector, action buttons, etc.
  children: React.ReactNode;          // tab content
}

/* ── Component ─────────────────────────────────────────────────── */

export default function TestbedViewShell({
  theme,
  tabs,
  activeTab,
  onTabChange,
  toolbarContent,
  children,
}: TestbedViewShellProps) {
  return (
    <div
      className="testbed-shell"
      style={{
        '--testbed-primary': theme.primary,
        '--testbed-dark': theme.dark,
        '--testbed-light': theme.light,
      } as React.CSSProperties}
    >
      {/* Header */}
      <div className="testbed-header">
        <div className="testbed-header-brand">
          {theme.logoDark ? (
            <>
              <img
                src={theme.logo}
                alt={theme.logoAlt}
                className="testbed-header-logo testbed-logo-light-mode"
              />
              <img
                src={theme.logoDark}
                alt={theme.logoAlt}
                className="testbed-header-logo testbed-logo-dark-mode"
              />
            </>
          ) : (
            <img
              src={theme.logo}
              alt={theme.logoAlt}
              className="testbed-header-logo"
            />
          )}
          <span className="testbed-header-name">{theme.name}</span>
        </div>

        {/* Tabs */}
        <div className="testbed-tabs">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`testbed-tab${activeTab === tab.id ? ' active' : ''}`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
              {tab.badge != null && tab.badge > 0 && (
                <span className="testbed-tab-badge">{tab.badge}</span>
              )}
            </button>
          ))}
        </div>

        {/* Toolbar slot */}
        {toolbarContent && (
          <div className="testbed-toolbar">
            {toolbarContent}
          </div>
        )}
      </div>

      {/* Content */}
      <div className="testbed-content">
        {children}
      </div>
    </div>
  );
}
