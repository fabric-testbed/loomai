'use client';
import React, { useState, useRef, useEffect } from 'react';
import '../styles/titlebar.css';
import { VERSION } from '../version';
import { checkForUpdate } from '../api/client';
import { assetUrl } from '../utils/assetUrl';
import type { UpdateInfo } from '../types/fabric';

interface AiToolInfo {
  id: string;
  name: string;
  icon: string;
}

type TopView = 'landing' | 'slices' | 'artifacts' | 'infrastructure' | 'jupyter' | 'ai' | 'chameleon';

interface TitleBarProps {
  dark: boolean;
  currentView: TopView;
  onToggleDark: () => void;
  onViewChange: (view: TopView) => void;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
  onGoHome: () => void;
  aiTools?: AiToolInfo[];
  selectedAiTool?: string | null;
  chameleonEnabled?: boolean;
  compositeEnabled?: boolean;
  onLaunchAiTool?: (toolId: string) => void;
  hasToken?: boolean;
  tokenExpired?: boolean;
  userEmail?: string;
  userName?: string;
  onLogout?: () => void;
}

const VIEWS: Array<{ key: TopView; label: string; icon: string; desc: string; requiresChameleon?: boolean; requiresComposite?: boolean }> = [
  { key: 'slices', label: 'Federated Slice', icon: '__composite_icon__', desc: 'Federated Slice — build, monitor, transfer files, and launch apps', requiresComposite: true },
  { key: 'infrastructure', label: 'FABRIC', icon: '__fabric_logo__', desc: 'FABRIC — testbed slices, resources, and availability' },
  { key: 'chameleon', label: 'Chameleon', icon: '__chameleon_logo__', desc: 'Chameleon Cloud — leases, instances, and bare-metal resources', requiresChameleon: true },
  { key: 'artifacts', label: 'Marketplace', icon: '__marketplace_icon__', desc: 'Marketplace — browse, publish, and download experiment artifacts' },
  { key: 'jupyter', label: 'JupyterLab', icon: '__jupyter_logo__', desc: 'JupyterLab — interactive notebooks' },
];

function ViewIcon({ icon, size = 12, dark }: { icon: string; size?: number; dark?: boolean }) {
  if (icon === '__fabric_logo__') {
    const src = dark ? assetUrl('/fabric_wave_light.png') : assetUrl('/fabric_wave_dark.png');
    return <img src={src} alt="" style={{ height: size, verticalAlign: 'middle' }} />;
  }
  if (icon === '__jupyter_logo__') {
    return <img src={assetUrl('/jupyter-icon.svg')} alt="" style={{ height: size, verticalAlign: 'middle' }} />;
  }
  if (icon === '__chameleon_logo__') {
    return <img src={assetUrl('/chameleon-icon.png')} alt="" style={{ height: size, verticalAlign: 'middle' }} />;
  }
  if (icon === '__loomai_icon__') {
    return <img src={assetUrl('/loomai-icon-transparent.svg')} alt="" style={{ height: size, verticalAlign: 'middle' }} />;
  }
  if (icon === '__composite_icon__') {
    return <img src={assetUrl('/loomai-icon-transparent.svg')} alt="" style={{ height: size, verticalAlign: 'middle' }} />;
  }
  if (icon === '__marketplace_icon__') {
    return <img src={assetUrl('/marketplace-icon-transparent.svg')} alt="" style={{ height: size, verticalAlign: 'middle' }} />;
  }
  return <>{icon}</>;
}

export default React.memo(function TitleBar({ dark, currentView, onToggleDark, onViewChange, onOpenSettings, onOpenHelp, onGoHome, aiTools, selectedAiTool, onLaunchAiTool, chameleonEnabled, compositeEnabled, hasToken, tokenExpired, userEmail, userName, onLogout }: TitleBarProps) {
  const isHubMode = typeof window !== 'undefined' && !!(window as any).__LOOMAI_BASE_PATH;
  const [viewOpen, setViewOpen] = useState(false);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [copiedPull, setCopiedPull] = useState(false);
  const [copiedRun, setCopiedRun] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [logoutConfirm, setLogoutConfirm] = useState(false);
  const viewRef = useRef<HTMLDivElement>(null);
  const updateRef = useRef<HTMLDivElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // Show the selected AI tool name in the pill when an AI view is active
  const activeAiTool = aiTools?.find((t) => t.id === selectedAiTool);
  const activeView = VIEWS.find((v) => v.key === currentView);

  // Check for updates on mount
  useEffect(() => {
    checkForUpdate().then(setUpdateInfo).catch(() => {});
  }, []);

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (viewRef.current && !viewRef.current.contains(e.target as Node)) setViewOpen(false);
      if (updateRef.current && !updateRef.current.contains(e.target as Node)) setUpdateOpen(false);
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
        setLogoutConfirm(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleVersionClick = () => {
    setUpdateOpen(!updateOpen);
  };

  const handleCopyPull = () => {
    navigator.clipboard.writeText('docker compose pull\ndocker compose up -d').then(() => {
      setCopiedPull(true);
      setTimeout(() => setCopiedPull(false), 2000);
    });
  };

  const handleCopyRun = () => {
    navigator.clipboard.writeText('docker pull fabrictestbed/loomai:latest\ndocker run -d -p 3000:3000 \\\n  -v fabric_work:/home/fabric/work \\\n  fabrictestbed/loomai:latest').then(() => {
      setCopiedRun(true);
      setTimeout(() => setCopiedRun(false), 2000);
    });
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '';
    try {
      return new Date(dateStr).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return dateStr;
    }
  };

  // Add "(beta)" suffix for versions starting with 0
  const displayVersion = (v: string) => {
    const clean = v.replace(/^v/, '');
    return clean.startsWith('0.') ? `${clean} (beta)` : clean;
  };

  return (
    <div className="title-bar">
      <div className="title-left">
        <span className="loomai-header-brand" onClick={onGoHome} style={{ cursor: 'pointer' }} title="Go to LoomAI home">
          <img src={assetUrl('/loomai-icon-transparent.svg')} alt="" className="loomai-header-icon" />
          <img src={assetUrl('/loomai-wordmark-transparent-dark-ink-trimmed.svg')} alt="LoomAI" className="loomai-header-wordmark" />
        </span>
        <div className="title-version-wrapper" ref={updateRef}>
          <button className="title-version-btn" onClick={handleVersionClick} title="Version info and updates">
            <span className="title-version">v{displayVersion(VERSION)}</span>
            {updateInfo?.update_available && <span className="title-update-badge" />}
          </button>
          {updateOpen && (
            <div className="title-update-panel">
              {updateInfo?.update_available ? (
                <>
                  <div className="title-update-header">Update Available</div>
                  <div className="title-update-versions">
                    <span className="title-update-current">v{displayVersion(updateInfo.current_version)}</span>
                    <span className="title-update-arrow">{'\u2192'}</span>
                    <span className="title-update-latest">v{displayVersion(updateInfo.latest_version)}</span>
                  </div>
                  {updateInfo.published_at && (
                    <div className="title-update-date">Published {formatDate(updateInfo.published_at)}</div>
                  )}
                </>
              ) : (
                <>
                  <div className="title-update-header title-update-header-current">
                    LoomAI v{displayVersion(VERSION)}
                  </div>
                  <div className="title-update-status-ok">{'\u2713'} You are running the latest version</div>
                </>
              )}
              {!window.__LOOMAI_BASE_PATH && (
                <>
                  <div className="title-update-divider" />
                  <div className="title-update-section-label">Update to latest:</div>
                  <div className="title-update-command">
                    <pre>docker compose pull{'\n'}docker compose up -d</pre>
                    <button className="title-update-copy" onClick={handleCopyPull}>
                      {copiedPull ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                  <div className="title-update-divider" />
                  <div className="title-update-section-label">Fresh install:</div>
                  <div className="title-update-command">
                    <pre>docker pull fabrictestbed/loomai:latest{'\n'}docker run -d -p 3000:3000 \{'\n'}  -v fabric_work:/home/fabric/work \{'\n'}  fabrictestbed/loomai:latest</pre>
                    <button className="title-update-copy" onClick={handleCopyRun}>
                      {copiedRun ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </>
              )}
              <div className="title-update-divider" />
              <div className="title-update-links">
                <a
                  className="title-update-link"
                  href={updateInfo?.docker_hub_url || `https://hub.docker.com/r/fabrictestbed/loomai`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View on Docker Hub {'\u2197'}
                </a>
                <a
                  className="title-update-link"
                  href="https://github.com/fabric-testbed/loomai"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View on GitHub {'\u2197'}
                </a>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="title-right">
        {/* View selector pill */}
        <div className="title-pill-wrapper" ref={viewRef} data-help-id="titlebar.view">
          <button className="title-pill" onClick={() => setViewOpen(!viewOpen)}>
            <span className="title-pill-label">View</span>
            <span className="title-pill-value">
              {currentView === 'ai' && activeAiTool
                ? <>{activeAiTool.icon.startsWith('__') ? <ViewIcon icon={activeAiTool.icon} size={12} dark={dark} /> : activeAiTool.icon} {activeAiTool.name}</>
                : <>{activeView && <ViewIcon icon={activeView.icon} size={12} dark={dark} />} {activeView?.label}</>}
            </span>
            <span className="title-pill-arrow">{viewOpen ? '\u25B4' : '\u25BE'}</span>
          </button>
          {viewOpen && (
            <div className="title-pill-dropdown">
              {VIEWS.filter(v => (!v.requiresChameleon || chameleonEnabled) && (!v.requiresComposite || compositeEnabled)).map((v) => {
                const isJupyter = v.key === 'jupyter';
                const handleClick = () => {
                  if (isJupyter) {
                    const base = (typeof window !== 'undefined' && (window as any).__LOOMAI_BASE_PATH) || '';
                    window.open(`${base}/jupyter/lab`, '_blank', 'noopener');
                  } else {
                    onViewChange(v.key);
                  }
                  setViewOpen(false);
                };
                return (
                  <button
                    key={v.key}
                    className={`title-pill-option ${!isJupyter && currentView === v.key ? 'active' : ''}`}
                    onClick={handleClick}
                    title={isJupyter ? `${v.desc} (opens in a new tab)` : v.desc}
                  >
                    <span className="title-pill-option-icon">
                      <ViewIcon icon={v.icon} size={12} dark={dark} />
                    </span>
                    {v.label}
                    {isJupyter && <span className="title-pill-check" aria-hidden>{'\u2197'}</span>}
                    {!isJupyter && currentView === v.key && <span className="title-pill-check">{'\u2713'}</span>}
                  </button>
                );
              })}
              {aiTools && aiTools.length > 0 && (
                <>
                  <div className="title-pill-section-header">AI Tools</div>
                  {aiTools.map((tool) => {
                    const hubDisabled = isHubMode && tool.id !== 'loomai';
                    return (
                    <button
                      key={tool.id}
                      className={`title-pill-option ${currentView === 'ai' && selectedAiTool === tool.id ? 'active' : ''}${hubDisabled ? ' hub-disabled' : ''}`}
                      onClick={hubDisabled ? undefined : () => { onLaunchAiTool?.(tool.id); setViewOpen(false); }}
                      disabled={hubDisabled}
                      title={hubDisabled ? 'Install LoomAI locally with Docker to use this tool — github.com/fabric-testbed/loomai' : undefined}
                    >
                      <span className="title-pill-option-icon">
                        {tool.icon.startsWith('__') ? <ViewIcon icon={tool.icon} size={12} dark={dark} /> : tool.icon}
                      </span>
                      {tool.name}
                      {hubDisabled
                        ? <span className={`title-pill-ai-tag ${tool.id === 'claude' ? 'paid' : 'local-only'}`}>
                            {tool.id === 'claude' ? 'Paid' : 'Local Only'}
                          </span>
                        : <span className={`title-pill-ai-tag ${tool.id === 'claude' ? 'paid' : 'free'}`}>
                            {tool.id === 'claude' ? 'Paid' : 'Free'}
                          </span>}
                      {currentView === 'ai' && selectedAiTool === tool.id && <span className="title-pill-check">{'\u2713'}</span>}
                    </button>
                    );
                  })}
                </>
              )}
            </div>
          )}
        </div>

        {/* User pill -- opens a dropdown with Settings / Help / Theme / Sign out.
            All title-bar account actions live here so the title bar is not
            cluttered with tiny circular icons (and the Sign-out action is
            behind a confirmation, not one click away from the gear). */}
        <div className="title-user-menu-wrapper" ref={userMenuRef}>
          <button
            className={
              'title-user-pill title-user-pill-btn'
              + (tokenExpired ? ' title-token-expired-pill' : '')
              + (!hasToken && !tokenExpired ? ' title-token-none-pill' : '')
            }
            onClick={() => { setUserMenuOpen(!userMenuOpen); setLogoutConfirm(false); }}
            title={userName || userEmail || 'Account menu'}
            data-help-id="titlebar.user"
          >
            {hasToken && !tokenExpired ? (
              <span className="title-token-status title-token-active">Active</span>
            ) : tokenExpired ? (
              <span className="title-token-status title-token-expired">Expired</span>
            ) : (
              <span className="title-token-status title-token-none">No Token</span>
            )}
            {userEmail && hasToken && !tokenExpired && (
              <>
                <span className="title-user-avatar">{(userName || userEmail).charAt(0).toUpperCase()}</span>
                <span className="title-user-email">{userEmail}</span>
              </>
            )}
            {userEmail && tokenExpired && <span className="title-user-email">{userEmail}</span>}
            <span className="title-pill-arrow">{userMenuOpen ? '\u25B4' : '\u25BE'}</span>
          </button>
          {userMenuOpen && (
            <div className="title-user-menu">
              <button
                className="title-user-menu-item"
                onClick={() => { setUserMenuOpen(false); onOpenSettings(); }}
                data-help-id="titlebar.settings"
              >
                <span className="title-user-menu-icon">{'\u2699'}</span> Settings
              </button>
              <button
                className="title-user-menu-item"
                onClick={() => { setUserMenuOpen(false); onOpenHelp(); }}
                data-help-id="titlebar.help"
              >
                <span className="title-user-menu-icon">?</span> Help
              </button>
              <button
                className="title-user-menu-item"
                onClick={onToggleDark}
                data-help-id="titlebar.theme"
              >
                <span className="title-user-menu-icon">{dark ? '\u2600' : '\u263E'}</span>
                {dark ? 'Light mode' : 'Dark mode'}
              </button>
              {onLogout && (
                <>
                  <div className="title-user-menu-divider" />
                  {logoutConfirm ? (
                    <div className="title-user-menu-confirm">
                      <span className="title-user-menu-confirm-text">
                        {isHubMode ? 'Stop server and sign out?' : 'Sign out?'}
                      </span>
                      <div className="title-user-menu-confirm-actions">
                        <button
                          className="title-user-menu-confirm-no"
                          onClick={() => setLogoutConfirm(false)}
                        >Cancel</button>
                        <button
                          className="title-user-menu-confirm-yes"
                          onClick={() => { setUserMenuOpen(false); setLogoutConfirm(false); onLogout(); }}
                        >Sign out</button>
                      </div>
                    </div>
                  ) : (
                    <button
                      className="title-user-menu-item title-user-menu-item-danger"
                      onClick={() => setLogoutConfirm(true)}
                    >
                      <span className="title-user-menu-icon">{'\u23FB'}</span>
                      {isHubMode ? 'Stop server & sign out' : 'Sign out'}
                    </button>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
