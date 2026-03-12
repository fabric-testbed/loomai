'use client';
import React, { useState, useRef, useEffect } from 'react';
import '../styles/titlebar.css';
import { VERSION } from '../version';
import { checkForUpdate } from '../api/client';
import type { UpdateInfo } from '../types/fabric';

interface ProjectInfo {
  uuid: string;
  name: string;
}

interface AiToolInfo {
  id: string;
  name: string;
  icon: string;
}

type TopView = 'landing' | 'slices' | 'artifacts' | 'infrastructure' | 'jupyter' | 'ai';

interface TitleBarProps {
  dark: boolean;
  currentView: TopView;
  onToggleDark: () => void;
  onViewChange: (view: TopView) => void;
  onOpenSettings: () => void;
  onOpenHelp: () => void;
  onGoHome: () => void;
  projectName?: string;
  projects?: ProjectInfo[];
  onProjectChange?: (uuid: string) => void;
  aiTools?: AiToolInfo[];
  selectedAiTool?: string | null;
  onLaunchAiTool?: (toolId: string) => void;
}

const VIEWS: Array<{ key: TopView; label: string; icon: string; desc: string }> = [
  { key: 'slices', label: 'Slices', icon: '\u25A6', desc: 'Slices — build, monitor, transfer files, and launch apps' },
  { key: 'artifacts', label: 'Artifacts', icon: '\u29C9', desc: 'Artifacts — browse, edit, and publish artifacts' },
  { key: 'infrastructure', label: 'Infrastructure', icon: '\u25C9', desc: 'Infrastructure — FABRIC testbed resources and availability' },
  { key: 'jupyter', label: 'JupyterLab', icon: '\uD83D\uDCD3', desc: 'JupyterLab — interactive notebooks' },
];

export default React.memo(function TitleBar({ dark, currentView, onToggleDark, onViewChange, onOpenSettings, onOpenHelp, onGoHome, projectName, projects, onProjectChange, aiTools, selectedAiTool, onLaunchAiTool }: TitleBarProps) {
  const currentProject = projects?.find((p) => p.name === projectName);
  const [viewOpen, setViewOpen] = useState(false);
  const [projOpen, setProjOpen] = useState(false);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [copiedPull, setCopiedPull] = useState(false);
  const [copiedRun, setCopiedRun] = useState(false);
  const viewRef = useRef<HTMLDivElement>(null);
  const projRef = useRef<HTMLDivElement>(null);
  const updateRef = useRef<HTMLDivElement>(null);

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
      if (projRef.current && !projRef.current.contains(e.target as Node)) setProjOpen(false);
      if (updateRef.current && !updateRef.current.contains(e.target as Node)) setUpdateOpen(false);
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
    navigator.clipboard.writeText('docker pull fabrictestbed/loomai-dev:latest\ndocker run -d -p 3000:3000 \\\n  -v fabric_work:/home/fabric/work \\\n  fabrictestbed/loomai-dev:latest').then(() => {
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
        <img src="/fabric_logo.png" alt="FABRIC" className="fabric-logo" onClick={onGoHome} style={{ cursor: 'pointer' }} title="Go to LoomAI home" />
        <span className="title-text">LoomAI</span>
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
                <pre>docker pull fabrictestbed/loomai-dev:latest{'\n'}docker run -d -p 3000:3000 \{'\n'}  -v fabric_work:/home/fabric/work \{'\n'}  fabrictestbed/loomai-dev:latest</pre>
                <button className="title-update-copy" onClick={handleCopyRun}>
                  {copiedRun ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <div className="title-update-divider" />
              <div className="title-update-links">
                <a
                  className="title-update-link"
                  href={updateInfo?.docker_hub_url || `https://hub.docker.com/r/fabrictestbed/loomai-dev`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  View on Docker Hub {'\u2197'}
                </a>
                <a
                  className="title-update-link"
                  href="https://github.com/fabric-testbed/fabric-webgui"
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
          <button className="title-pill" onClick={() => { setViewOpen(!viewOpen); setProjOpen(false); }}>
            <span className="title-pill-label">View</span>
            <span className="title-pill-value">
              {currentView === 'ai' && activeAiTool
                ? <>{activeAiTool.icon} {activeAiTool.name}</>
                : <>{activeView?.icon} {activeView?.label}</>}
            </span>
            <span className="title-pill-arrow">{viewOpen ? '\u25B4' : '\u25BE'}</span>
          </button>
          {viewOpen && (
            <div className="title-pill-dropdown">
              {VIEWS.map((v) => (
                <button
                  key={v.key}
                  className={`title-pill-option ${currentView === v.key ? 'active' : ''}`}
                  onClick={() => { onViewChange(v.key); setViewOpen(false); }}
                  title={v.desc}
                >
                  <span className="title-pill-option-icon">{v.icon}</span>
                  {v.label}
                  {currentView === v.key && <span className="title-pill-check">{'\u2713'}</span>}
                </button>
              ))}
              {aiTools && aiTools.length > 0 && (
                <>
                  <div className="title-pill-section-header">AI Tools</div>
                  {aiTools.map((tool) => (
                    <button
                      key={tool.id}
                      className={`title-pill-option ${currentView === 'ai' && selectedAiTool === tool.id ? 'active' : ''}`}
                      onClick={() => { onLaunchAiTool?.(tool.id); setViewOpen(false); }}
                    >
                      <span className="title-pill-option-icon">{tool.icon}</span>
                      {tool.name}
                      <span className={`title-pill-ai-tag ${tool.id === 'claude' ? 'paid' : 'free'}`}>
                        {tool.id === 'claude' ? 'Paid' : 'Free'}
                      </span>
                      {currentView === 'ai' && selectedAiTool === tool.id && <span className="title-pill-check">{'\u2713'}</span>}
                    </button>
                  ))}
                </>
              )}
            </div>
          )}
        </div>

        {/* Project selector pill */}
        {projects && projects.length > 0 && onProjectChange && (
          <div className="title-pill-wrapper" ref={projRef} data-help-id="titlebar.project">
            <button className="title-pill" onClick={() => { setProjOpen(!projOpen); setViewOpen(false); }}>
              <span className="title-pill-label">Project</span>
              <span className="title-pill-value">{projectName || 'None'}</span>
              <span className="title-pill-arrow">{projOpen ? '\u25B4' : '\u25BE'}</span>
            </button>
            {projOpen && (
              <div className="title-pill-dropdown title-pill-dropdown-projects">
                {projects.map((p) => (
                  <button
                    key={p.uuid}
                    className={`title-pill-option ${currentProject?.uuid === p.uuid ? 'active' : ''}`}
                    onClick={() => { onProjectChange(p.uuid); setProjOpen(false); }}
                  >
                    {p.name}
                    {currentProject?.uuid === p.uuid && <span className="title-pill-check">{'\u2713'}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Settings button */}
        <button className="title-icon-btn" onClick={onOpenSettings} title="Settings" data-help-id="titlebar.settings">
          {'\u2699'}
        </button>

        {/* Theme toggle */}
        <button className="title-icon-btn" onClick={onToggleDark} title={dark ? 'Switch to light mode' : 'Switch to dark mode'} data-help-id="titlebar.theme">
          {dark ? '\u2600' : '\u263E'}
        </button>

        {/* Help button */}
        <button className="title-icon-btn" onClick={onOpenHelp} title="Help" data-help-id="titlebar.help">
          ?
        </button>
      </div>
    </div>
  );
});
