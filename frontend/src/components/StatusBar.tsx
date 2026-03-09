'use client';
import React from 'react';
import '../styles/status-bar.css';

interface StatusBarProps {
  statusMessage?: string;
  loading?: boolean;
  sliceState?: string;
  errorCount?: number;
  validationErrorCount?: number;
  warnCount?: number;
  terminalCount?: number;
  recipeRunning?: boolean;
  bootRunning?: boolean;
}

export default function StatusBar({
  statusMessage,
  loading,
  sliceState,
  errorCount = 0,
  validationErrorCount = 0,
  warnCount = 0,
  terminalCount = 0,
  recipeRunning,
  bootRunning,
}: StatusBarProps) {
  return (
    <div className="status-bar">
      <div className="sb-left">
        {statusMessage ? (
          <>
            <span className="sb-spinner" />
            <span className="sb-status-text">{statusMessage}</span>
          </>
        ) : loading ? (
          <span className="sb-spinner" />
        ) : null}
      </div>
      <div className="sb-right">
        {errorCount > 0 && (
          <span className="sb-badge error">{errorCount} error{errorCount !== 1 ? 's' : ''}</span>
        )}
        {validationErrorCount > 0 && (
          <span className="sb-badge warn">{validationErrorCount} validation</span>
        )}
        {warnCount > 0 && (
          <span className="sb-badge warn">{warnCount} warning{warnCount !== 1 ? 's' : ''}</span>
        )}
        {terminalCount > 0 && (
          <span className="sb-badge info">{terminalCount} terminal{terminalCount !== 1 ? 's' : ''}</span>
        )}
        {recipeRunning && <span className="sb-badge active">recipe</span>}
        {bootRunning && <span className="sb-badge active">boot config</span>}
        {sliceState && <span className="sb-slice-state">{sliceState}</span>}
      </div>
    </div>
  );
}
