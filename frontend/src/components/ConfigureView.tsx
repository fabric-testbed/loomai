'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import * as api from '../api/client';
import type { ConfigStatus, ProjectInfo, SliceKeySet, LoomAISettings, ToolConfigStatus } from '../types/fabric';
import '../styles/configure.css';

interface ConfigureViewProps {
  onConfigured: () => void;
  onClose?: () => void;
  hiddenProjects?: Set<string>;
  onHiddenProjectsChange?: (hidden: Set<string>) => void;
  /** Full project list from Core API (more complete than JWT-only list) */
  allProjects?: ProjectInfo[];
}

export default function ConfigureView({ onConfigured, onClose, hiddenProjects, onHiddenProjectsChange, allProjects }: ConfigureViewProps) {
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [bastionLogin, setBastionLogin] = useState('');
  const [selectedProject, setSelectedProject] = useState('');
  const [generatedPubKey, setGeneratedPubKey] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showTokenPaste, setShowTokenPaste] = useState(false);
  const [pastedToken, setPastedToken] = useState('');

  // Key set management
  const [keySets, setKeySets] = useState<SliceKeySet[]>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [showAddKeySet, setShowAddKeySet] = useState(false);

  // Advanced settings
  const [credmgrHost, setCredmgrHost] = useState('cm.fabric-testbed.net');
  const [orchestratorHost, setOrchestratorHost] = useState('orchestrator.fabric-testbed.net');
  const [coreApiHost, setCoreApiHost] = useState('uis.fabric-testbed.net');
  const [bastionHost, setBastionHost] = useState('bastion.fabric-testbed.net');
  const [amHost, setAmHost] = useState('artifacts.fabric-testbed.net');
  const [logLevel, setLogLevel] = useState('INFO');
  const [logFile, setLogFile] = useState('/tmp/fablib/fablib.log');
  const [avoidSet, setAvoidSet] = useState<Set<string>>(new Set());
  const [siteNames, setSiteNames] = useState<string[]>([]);
  const [sshCommandLine, setSshCommandLine] = useState(
    'ssh -i {{ _self_.private_ssh_key_file }} -F {config_dir}/ssh_config {{ _self_.username }}@{{ _self_.management_ip }}'
  );
  const [litellmApiKey, setLitellmApiKey] = useState('');
  const [nrpApiKey, setNrpApiKey] = useState('');
  const [aiTools, setAiTools] = useState<Record<string, boolean>>({
    aider: true, opencode: true, crush: true, claude: false,
  });

  // Unified settings and tool configs
  const [settings, setSettings] = useState<LoomAISettings | null>(null);
  const [toolConfigs, setToolConfigs] = useState<ToolConfigStatus[]>([]);

  // Path settings
  const [pathStorageDir, setPathStorageDir] = useState('');
  const [pathConfigDir, setPathConfigDir] = useState('');
  const [pathArtifactsDir, setPathArtifactsDir] = useState('');
  const [pathSlicesDir, setPathSlicesDir] = useState('');
  const [pathNotebooksDir, setPathNotebooksDir] = useState('');
  const [pathAiToolsDir, setPathAiToolsDir] = useState('');
  const [pathTokenFile, setPathTokenFile] = useState('');
  const [pathBastionKeyFile, setPathBastionKeyFile] = useState('');
  const [pathSliceKeysDir, setPathSliceKeysDir] = useState('');
  const [pathSshConfigFile, setPathSshConfigFile] = useState('');
  const [pathLogFile, setPathLogFile] = useState('');

  // Service settings
  const [aiServerUrl, setAiServerUrl] = useState('https://ai.fabric-testbed.net');
  const [nrpServerUrl, setNrpServerUrl] = useState('https://ellm.nrp-nautilus.io');
  const [jupyterPort, setJupyterPort] = useState(8889);
  const [modelProxyPort, setModelProxyPort] = useState(9199);

  const tokenFileRef = useRef<HTMLInputElement>(null);
  const bastionKeyRef = useRef<HTMLInputElement>(null);
  const slicePrivKeyRef = useRef<HTMLInputElement>(null);
  const slicePubKeyRef = useRef<HTMLInputElement>(null);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.getConfig();
      setStatus(s);
      if (s.project_id) setSelectedProject(s.project_id);
      if (s.bastion_username) setBastionLogin(s.bastion_username);
    } catch {
      // ignore on initial load
    }
  }, []);

  const loadKeySets = useCallback(async () => {
    try {
      const sets = await api.listSliceKeySets();
      setKeySets(sets);
    } catch {
      // ignore
    }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const s = await api.getSettings();
      setSettings(s);
      // Populate form fields from settings
      if (s.fabric.project_id) setSelectedProject(s.fabric.project_id);
      if (s.fabric.bastion_username) setBastionLogin(s.fabric.bastion_username);
      setCredmgrHost(s.fabric.hosts.credmgr);
      setOrchestratorHost(s.fabric.hosts.orchestrator);
      setCoreApiHost(s.fabric.hosts.core_api);
      setBastionHost(s.fabric.hosts.bastion);
      setAmHost(s.fabric.hosts.artifact_manager);
      setLogLevel(s.fabric.logging.level);
      setLogFile(s.paths.log_file);
      setSshCommandLine(s.fabric.ssh_command_line);
      setAvoidSet(new Set(s.fabric.avoid_sites));
      setAiTools(s.ai.tools);
      setAiServerUrl(s.ai.ai_server_url);
      setNrpServerUrl(s.ai.nrp_server_url);
      setJupyterPort(s.services.jupyter_port);
      setModelProxyPort(s.services.model_proxy_port);
      // Paths
      setPathStorageDir(s.paths.storage_dir);
      setPathConfigDir(s.paths.config_dir);
      setPathArtifactsDir(s.paths.artifacts_dir);
      setPathSlicesDir(s.paths.slices_dir);
      setPathNotebooksDir(s.paths.notebooks_dir);
      setPathAiToolsDir(s.paths.ai_tools_dir);
      setPathTokenFile(s.paths.token_file);
      setPathBastionKeyFile(s.paths.bastion_key_file);
      setPathSliceKeysDir(s.paths.slice_keys_dir);
      setPathSshConfigFile(s.paths.ssh_config_file);
      setPathLogFile(s.paths.log_file);
    } catch {
      // Settings may not exist yet on first run
    }
  }, []);

  const loadToolConfigs = useCallback(async () => {
    try {
      const configs = await api.getToolConfigs();
      setToolConfigs(configs);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadKeySets();
    loadSettings();
    loadToolConfigs();
  }, [loadStatus, loadKeySets, loadSettings, loadToolConfigs]);

  // Load projects when token is available
  const loadProjects = useCallback(async () => {
    try {
      const data = await api.getProjects();
      setProjects(data.projects);
      if (data.bastion_login) setBastionLogin(data.bastion_login);
      if (data.projects.length > 0) {
        setSelectedProject(data.projects[0].uuid);
      }
    } catch (e: any) {
      setMessage({ text: `Failed to load projects: ${e.message}`, type: 'error' });
    }
  }, []);

  useEffect(() => {
    if (status?.has_token) {
      loadProjects();
    }
  }, [status?.has_token, loadProjects]);

  // Load site names for avoid selector
  useEffect(() => {
    api.listSites().then((sites) => {
      setSiteNames(sites.map((s) => s.name).sort());
    }).catch(() => {});
  }, []);

  const toggleAvoidSite = (site: string) => {
    setAvoidSet((prev) => {
      const next = new Set(prev);
      if (next.has(site)) next.delete(site);
      else next.add(site);
      return next;
    });
  };

  const handleTokenUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      await api.uploadToken(file);
      setMessage({ text: 'Token uploaded successfully', type: 'success' });
      await loadStatus();
      await loadProjects();
    } catch (err: any) {
      setMessage({ text: `Token upload failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
      if (tokenFileRef.current) tokenFileRef.current.value = '';
    }
  };

  const handleOAuthLogin = async () => {
    try {
      const { login_url } = await api.getLoginUrl();
      window.open(login_url, '_blank');
      setShowTokenPaste(true);
    } catch (err: any) {
      setMessage({ text: `Login failed: ${err.message}`, type: 'error' });
    }
  };

  const handlePasteToken = async () => {
    if (!pastedToken.trim()) return;
    setLoading(true);
    try {
      await api.pasteToken(pastedToken);
      setMessage({ text: 'Token saved successfully', type: 'success' });
      setPastedToken('');
      setShowTokenPaste(false);
      await loadStatus();
      await loadProjects();
    } catch (err: any) {
      setMessage({ text: `Token paste failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleBastionKeyUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      await api.uploadBastionKey(file);
      setMessage({ text: 'Bastion key uploaded', type: 'success' });
      await loadStatus();
    } catch (err: any) {
      setMessage({ text: `Bastion key upload failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
      if (bastionKeyRef.current) bastionKeyRef.current.value = '';
    }
  };

  const handleSliceKeyUpload = async (keyName: string) => {
    const privFile = slicePrivKeyRef.current?.files?.[0];
    const pubFile = slicePubKeyRef.current?.files?.[0];
    if (!privFile || !pubFile) {
      setMessage({ text: 'Select both private and public key files', type: 'error' });
      return;
    }
    setLoading(true);
    try {
      await api.uploadSliceKeys(privFile, pubFile, keyName);
      setMessage({ text: `Slice keys uploaded to set '${keyName}'`, type: 'success' });
      await loadStatus();
      await loadKeySets();
      setShowAddKeySet(false);
      setNewKeyName('');
    } catch (err: any) {
      setMessage({ text: `Slice key upload failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
      if (slicePrivKeyRef.current) slicePrivKeyRef.current.value = '';
      if (slicePubKeyRef.current) slicePubKeyRef.current.value = '';
    }
  };

  const handleGenerateKeys = async (keyName: string) => {
    setLoading(true);
    try {
      const result = await api.generateSliceKeys(keyName);
      setGeneratedPubKey(result.public_key);
      setMessage({ text: result.message, type: 'success' });
      await loadStatus();
      await loadKeySets();
      setShowAddKeySet(false);
      setNewKeyName('');
    } catch (err: any) {
      setMessage({ text: `Key generation failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleSetDefault = async (name: string) => {
    try {
      await api.setDefaultSliceKey(name);
      setMessage({ text: `Default key set changed to '${name}'`, type: 'success' });
      await loadStatus();
      await loadKeySets();
    } catch (err: any) {
      setMessage({ text: `Failed to set default: ${err.message}`, type: 'error' });
    }
  };

  const handleDeleteKeySet = async (name: string) => {
    try {
      await api.deleteSliceKeySet(name);
      setMessage({ text: `Key set '${name}' deleted`, type: 'success' });
      await loadKeySets();
    } catch (err: any) {
      setMessage({ text: `Failed to delete: ${err.message}`, type: 'error' });
    }
  };

  const handleCopyPubKey = (pubKey: string) => {
    navigator.clipboard.writeText(pubKey);
    setMessage({ text: 'Public key copied to clipboard', type: 'success' });
  };

  const handleSave = async () => {
    if (!selectedProject) {
      setMessage({ text: 'Please select a project', type: 'error' });
      return;
    }
    if (!bastionLogin) {
      setMessage({ text: 'Bastion username is required', type: 'error' });
      return;
    }
    setSaving(true);
    try {
      // Build unified settings object
      const updatedSettings: LoomAISettings = {
        schema_version: settings?.schema_version ?? 1,
        paths: {
          storage_dir: pathStorageDir || settings?.paths.storage_dir || '/home/fabric/work',
          config_dir: pathConfigDir || settings?.paths.config_dir || '/home/fabric/work/fabric_config',
          artifacts_dir: pathArtifactsDir || settings?.paths.artifacts_dir || '/home/fabric/work/my_artifacts',
          slices_dir: pathSlicesDir || settings?.paths.slices_dir || '/home/fabric/work/my_slices',
          notebooks_dir: pathNotebooksDir || settings?.paths.notebooks_dir || '/home/fabric/work/notebooks',
          ai_tools_dir: pathAiToolsDir || settings?.paths.ai_tools_dir || '/home/fabric/work/.ai-tools',
          token_file: pathTokenFile || settings?.paths.token_file || '/home/fabric/work/fabric_config/id_token.json',
          bastion_key_file: pathBastionKeyFile || settings?.paths.bastion_key_file || '/home/fabric/work/fabric_config/fabric_bastion_key',
          slice_keys_dir: pathSliceKeysDir || settings?.paths.slice_keys_dir || '/home/fabric/work/fabric_config/slice_keys',
          ssh_config_file: pathSshConfigFile || settings?.paths.ssh_config_file || '/home/fabric/work/fabric_config/ssh_config',
          log_file: pathLogFile || logFile,
        },
        fabric: {
          project_id: selectedProject,
          bastion_username: bastionLogin,
          hosts: {
            credmgr: credmgrHost,
            orchestrator: orchestratorHost,
            core_api: coreApiHost,
            bastion: bastionHost,
            artifact_manager: amHost,
          },
          logging: { level: logLevel },
          avoid_sites: Array.from(avoidSet),
          ssh_command_line: sshCommandLine,
        },
        ai: {
          fabric_api_key: litellmApiKey || settings?.ai.fabric_api_key || '',
          nrp_api_key: nrpApiKey || settings?.ai.nrp_api_key || '',
          ai_server_url: aiServerUrl,
          nrp_server_url: nrpServerUrl,
          tools: aiTools,
        },
        services: {
          jupyter_port: jupyterPort,
          model_proxy_port: modelProxyPort,
        },
        tool_configs: settings?.tool_configs ?? {},
      };

      // Save via unified settings API (writes settings.json + regenerates fabric_rc + ssh_config)
      await api.saveSettings(updatedSettings);

      // Also save via legacy endpoint to ensure FABlib reset happens
      const result = await api.saveConfig({
        project_id: selectedProject,
        bastion_username: bastionLogin,
        credmgr_host: credmgrHost,
        orchestrator_host: orchestratorHost,
        core_api_host: coreApiHost,
        bastion_host: bastionHost,
        am_host: amHost,
        log_level: logLevel,
        log_file: logFile,
        avoid: Array.from(avoidSet).join(','),
        ssh_command_line: sshCommandLine,
        litellm_api_key: litellmApiKey,
        nrp_api_key: nrpApiKey,
      });
      if (result.configured) {
        setMessage({ text: 'Configuration saved! FABRIC is ready.', type: 'success' });
        await loadStatus();
        onConfigured();
      } else {
        setMessage({ text: 'Configuration saved but some items are still missing.', type: 'error' });
        await loadStatus();
      }
    } catch (err: any) {
      setMessage({ text: `Save failed: ${err.message}`, type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const tokenExpiry = status?.token_info?.exp
    ? new Date(status.token_info.exp * 1000).toLocaleString()
    : null;

  const effectiveKeyName = showAddKeySet && newKeyName.trim() ? newKeyName.trim() : 'default';

  return (
    <div className="configure-view">
      <div className="configure-card">
        {/* Header */}
        <div className="configure-header">
          <h2 className="configure-title">{'\u2699'} Settings</h2>
          <div className="configure-header-actions">
            <button
              className="btn primary"
              onClick={async () => { await handleSave(); onClose?.(); }}
              disabled={saving || !status?.has_token || !selectedProject || !bastionLogin}
            >
              {saving ? 'Saving...' : 'Save & Close'}
            </button>
            {onClose && (
              <button className="btn configure-close-btn" onClick={onClose}>
                Close
              </button>
            )}
          </div>
        </div>

        {/* Status Banner */}
        <div className="status-banner">
          <div className="status-item">
            <span className={`status-dot ${status?.has_token ? 'ok' : 'missing'}`} />
            Token
          </div>
          <div className="status-item">
            <span className={`status-dot ${status?.has_bastion_key ? 'ok' : 'missing'}`} />
            Bastion Key
          </div>
          <div className="status-item">
            <span className={`status-dot ${status?.has_slice_key ? 'ok' : 'missing'}`} />
            Slice Keys
          </div>
          <div className="status-item">
            <span className={`status-dot ${selectedProject ? 'ok' : 'missing'}`} />
            Project
          </div>
        </div>

        {/* Global message */}
        {message && (
          <div className={`configure-section message ${message.type}`}>
            {message.text}
          </div>
        )}

        {/* Identity & Project Section */}
        <div className="configure-section" data-tour-id="token">
          <h3>Identity and Project</h3>
          <p>Upload a token file, or login with FABRIC to get a token from Credential Manager.</p>
          <div className="btn-row">
            <input
              ref={tokenFileRef}
              type="file"
              accept=".json"
              className="file-input-hidden"
              onChange={handleTokenUpload}
            />
            <button
              className="btn"
              onClick={() => tokenFileRef.current?.click()}
              disabled={loading}
              title="Upload id_token.json from FABRIC Credential Manager"
            >
              Upload Token File
            </button>
            <button
              className="btn"
              onClick={handleOAuthLogin}
              disabled={loading}
              title="Open FABRIC Credential Manager to get a token"
            >
              Login via FABRIC
            </button>
          </div>
          {showTokenPaste && (
            <div style={{ marginTop: 12 }}>
              <p>Credential Manager opened in a new tab. After logging in, copy the token JSON and paste it below.</p>
              <textarea
                className="token-paste-area"
                value={pastedToken}
                onChange={(e) => setPastedToken(e.target.value)}
                placeholder='Paste the token JSON here, e.g. {"id_token": "...", "refresh_token": "..."}'
                rows={4}
              />
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button
                  className="btn primary"
                  onClick={handlePasteToken}
                  disabled={loading || !pastedToken.trim()}
                >
                  {loading ? 'Saving...' : 'Save Token'}
                </button>
                <button
                  className="btn"
                  onClick={() => { setShowTokenPaste(false); setPastedToken(''); }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {status?.token_info && !status.token_info.error && (
            <div className="token-info">
              {status.token_info.name && <span>User: {status.token_info.name}</span>}
              {status.token_info.email && <span>Email: {status.token_info.email}</span>}
              {status.token_info.uuid && <span>Account: {status.token_info.uuid.slice(0, 8)}</span>}
              {tokenExpiry && <span>Expires: {tokenExpiry}</span>}
            </div>
          )}

          <p style={{ marginTop: 16 }}><strong>Project</strong> — Select your FABRIC project.</p>
          <select
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
            disabled={projects.length === 0}
            data-help-id="settings.project"
          >
            <option value="">-- Select Project --</option>
            {projects.map((p) => (
              <option key={p.uuid} value={p.uuid}>
                {p.name} ({p.uuid.slice(0, 8)}...)
              </option>
            ))}
          </select>
          {projects.length === 0 && status?.has_token && (
            <p>Loading projects from token...</p>
          )}

          {/* Project Visibility */}
          {(allProjects || projects).length > 1 && onHiddenProjectsChange && (
            <>
              <p style={{ marginTop: 16 }} data-help-id="settings.project-visibility"><strong>Visible Projects</strong> — Toggle projects on or off to control which appear in the project switcher.</p>
              <div className="project-toggle-list">
                {(allProjects || projects).map((p) => {
                  const isHidden = hiddenProjects?.has(p.uuid) ?? false;
                  const isActive = p.uuid === selectedProject;
                  return (
                    <label key={p.uuid} className={`project-toggle-row${isHidden ? ' hidden-project' : ''}`}>
                      <input
                        type="checkbox"
                        checked={!isHidden}
                        disabled={isActive}
                        onChange={() => {
                          const next = new Set(hiddenProjects);
                          if (isHidden) next.delete(p.uuid);
                          else next.add(p.uuid);
                          onHiddenProjectsChange(next);
                        }}
                      />
                      <span className="project-toggle-name">{p.name}</span>
                      {isActive && <span className="project-toggle-active">active</span>}
                    </label>
                  );
                })}
              </div>
            </>
          )}

          <p style={{ marginTop: 16 }}><strong>Bastion Username</strong> — Your FABRIC bastion login username (auto-detected from token when possible).</p>
          <input
            type="text"
            value={bastionLogin}
            onChange={(e) => setBastionLogin(e.target.value)}
            placeholder="e.g. user_name_0001234567"
            title="Your FABRIC bastion login (auto-detected from token)"
          />
        </div>

        {/* SSH Keys Section */}
        <div className="configure-section">
          <h3>SSH Keys</h3>

          {/* Bastion Key */}
          <p data-tour-id="bastion-key"><strong>Bastion Key</strong> — Upload your FABRIC bastion private key (from the portal).</p>
          <div className="btn-row">
            <input
              ref={bastionKeyRef}
              type="file"
              className="file-input-hidden"
              onChange={handleBastionKeyUpload}
            />
            <button
              className="btn"
              onClick={() => bastionKeyRef.current?.click()}
              disabled={loading}
            >
              Upload Bastion Key
            </button>
            {status?.has_bastion_key && <span className="status-item"><span className="status-dot ok" /> Uploaded</span>}
          </div>
          {status?.bastion_key_fingerprint && (
            <div className="key-info">
              <span className="key-info-label">Fingerprint:</span> {status.bastion_key_fingerprint}
              {status?.bastion_pub_key && (
                <button className="btn-sm" style={{ marginLeft: 8 }} onClick={() => handleCopyPubKey(status.bastion_pub_key!)}>Copy Public Key</button>
              )}
            </div>
          )}

          {/* Slice Key Sets */}
          <p style={{ marginTop: 16 }} data-tour-id="slice-keys"><strong>Slice Key Sets</strong> — Manage named SSH key pairs for slice access.</p>

          {/* Key Set List */}
          {keySets.length > 0 && (
            <div className="key-set-list">
              {keySets.map((ks) => (
                <div key={ks.name} className="key-set-row">
                  <div className="key-set-info">
                    <span className="key-set-name">{ks.name}</span>
                    {ks.is_default && <span className="key-set-default-badge">default</span>}
                    {ks.fingerprint && (
                      <span className="key-set-fingerprint">{ks.fingerprint}</span>
                    )}
                  </div>
                  <div className="key-set-actions">
                    {ks.pub_key && (
                      <button className="btn-sm" onClick={() => handleCopyPubKey(ks.pub_key)} title="Copy public key">
                        Copy Pub
                      </button>
                    )}
                    {!ks.is_default && (
                      <>
                        <button className="btn-sm primary" onClick={() => handleSetDefault(ks.name)} title="Set as default">
                          Set Default
                        </button>
                        <button className="btn-sm danger" onClick={() => handleDeleteKeySet(ks.name)} title="Delete key set">
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Add Key Set */}
          {!showAddKeySet ? (
            <div className="btn-row" style={{ marginTop: 8 }}>
              <button className="btn" onClick={() => setShowAddKeySet(true)} disabled={loading}>
                Add Key Set
              </button>
            </div>
          ) : (
            <div className="add-key-set-form">
              <div className="btn-row">
                <input
                  type="text"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))}
                  placeholder="Key set name (e.g. project-x)"
                  style={{ flex: 1, marginBottom: 0 }}
                />
                <button className="btn" onClick={() => { setShowAddKeySet(false); setNewKeyName(''); }}>
                  Cancel
                </button>
              </div>
              <input ref={slicePrivKeyRef} type="file" className="file-input-hidden" />
              <input ref={slicePubKeyRef} type="file" className="file-input-hidden" />
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button
                  className="btn"
                  onClick={() => slicePrivKeyRef.current?.click()}
                  disabled={loading}
                >
                  Private Key
                </button>
                <button
                  className="btn"
                  onClick={() => slicePubKeyRef.current?.click()}
                  disabled={loading}
                >
                  Public Key
                </button>
                <button
                  className="btn"
                  onClick={() => handleSliceKeyUpload(effectiveKeyName)}
                  disabled={loading}
                >
                  Upload Pair
                </button>
                <button className="btn success" onClick={() => handleGenerateKeys(effectiveKeyName)} disabled={loading}>
                  Generate
                </button>
              </div>
            </div>
          )}

          {generatedPubKey && (
            <div className="key-info" style={{ marginTop: 8 }}>
              <span className="key-info-label">Generated key ready.</span>
              <button className="btn-sm" style={{ marginLeft: 8 }} onClick={() => handleCopyPubKey(generatedPubKey)}>Copy Public Key</button>
            </div>
          )}
        </div>

        {/* Advanced Settings */}
        <div className="configure-section">
          <button className="advanced-toggle" onClick={() => setShowAdvanced(!showAdvanced)}>
            {showAdvanced ? 'Hide' : 'Show'} Advanced Settings
          </button>
          {showAdvanced && (
            <div style={{ marginTop: 12 }}>
              <p>Credential Manager Host</p>
              <input type="text" value={credmgrHost} onChange={(e) => setCredmgrHost(e.target.value)} />
              <p>Orchestrator Host</p>
              <input type="text" value={orchestratorHost} onChange={(e) => setOrchestratorHost(e.target.value)} />
              <p>Core API Host</p>
              <input type="text" value={coreApiHost} onChange={(e) => setCoreApiHost(e.target.value)} />
              <p>Bastion Host</p>
              <input type="text" value={bastionHost} onChange={(e) => setBastionHost(e.target.value)} />
              <p>Artifact Manager Host</p>
              <input type="text" value={amHost} onChange={(e) => setAmHost(e.target.value)} />
              <p>Log Level</p>
              <select value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
                <option>DEBUG</option>
                <option>INFO</option>
                <option>WARNING</option>
                <option>ERROR</option>
              </select>
              <p>Log File</p>
              <input type="text" value={logFile} onChange={(e) => setLogFile(e.target.value)} />
              <p data-help-id="settings.avoid-sites">Sites to Avoid</p>
              <div className="site-toggle-grid">
                {siteNames.map((site) => (
                  <button
                    key={site}
                    className={`site-toggle ${avoidSet.has(site) ? 'avoided' : ''}`}
                    onClick={() => toggleAvoidSite(site)}
                    type="button"
                  >
                    {site}
                  </button>
                ))}
              </div>
              {avoidSet.size > 0 && (
                <p style={{ marginTop: 4, marginBottom: 0, fontSize: 12 }}>
                  Avoiding: {Array.from(avoidSet).sort().join(', ')}
                </p>
              )}
              <p>SSH Command Line</p>
              <input type="text" value={sshCommandLine} onChange={(e) => setSshCommandLine(e.target.value)} />

              <p style={{ marginTop: 16, fontWeight: 600 }} data-help-id="settings.tour">Getting Started Tour</p>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer', marginTop: 4 }}>
                <input
                  type="checkbox"
                  checked={localStorage.getItem('fabric-tour-dismissed') !== 'true'}
                  onChange={(e) => {
                    if (e.target.checked) {
                      localStorage.removeItem('fabric-tour-dismissed');
                    } else {
                      localStorage.setItem('fabric-tour-dismissed', 'true');
                    }
                  }}
                />
                Show guided tour on next session
              </label>

              <p style={{ marginTop: 16, fontWeight: 600 }}>AI Companion</p>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, marginBottom: 6 }} data-help-id="settings.ai-api-key">
                API key for FABRIC AI services (ai.fabric-testbed.net). Used by Aider, OpenCode, and Crush.
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="password"
                  value={litellmApiKey}
                  onChange={(e) => setLitellmApiKey(e.target.value)}
                  placeholder="Enter FABRIC AI API key..."
                  style={{ flex: 1 }}
                />
                {status?.ai_api_key_set && !litellmApiKey && (
                  <span style={{ fontSize: 12, color: '#008e7a', whiteSpace: 'nowrap' }}>{'\u2713'} Configured</span>
                )}
              </div>

              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 10, marginBottom: 6 }} data-help-id="settings.nrp-api-key">
                API key for NRP LLM services (nrp.ai). Adds additional models to all AI tools.
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="password"
                  value={nrpApiKey}
                  onChange={(e) => setNrpApiKey(e.target.value)}
                  placeholder="Enter NRP API key..."
                  style={{ flex: 1 }}
                />
                {status?.nrp_api_key_set && !nrpApiKey && (
                  <span style={{ fontSize: 12, color: '#008e7a', whiteSpace: 'nowrap' }}>{'\u2713'} Configured</span>
                )}
              </div>

              <p style={{ marginTop: 16, fontWeight: 600 }}>AI Server URLs</p>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, marginBottom: 6 }}>
                Server endpoints for AI model access.
              </p>
              <p style={{ fontSize: 12, marginTop: 8 }}>FABRIC AI Server URL</p>
              <input type="text" value={aiServerUrl} onChange={(e) => setAiServerUrl(e.target.value)} />
              <p style={{ fontSize: 12, marginTop: 8 }}>NRP Server URL</p>
              <input type="text" value={nrpServerUrl} onChange={(e) => setNrpServerUrl(e.target.value)} />

              <p style={{ marginTop: 12, fontWeight: 600, fontSize: 13 }} data-help-id="settings.ai-tools">Enabled Tools</p>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, marginBottom: 8 }}>
                Choose which AI tools appear in the AI Companion launcher.
              </p>
              <div className="ai-tool-toggles">
                {([
                  { id: 'aider', label: 'Aider', desc: 'AI pair programming terminal' },
                  { id: 'opencode', label: 'OpenCode', desc: 'Terminal-based AI coding assistant' },
                  { id: 'crush', label: 'Crush', desc: 'Terminal AI assistant (Charm)' },
                  { id: 'claude', label: 'Claude Code', desc: 'Anthropic CLI (requires your own account)' },
                ] as const).map((tool) => (
                  <label key={tool.id} className="ai-tool-toggle-row">
                    <input
                      type="checkbox"
                      checked={aiTools[tool.id] ?? false}
                      onChange={(e) => setAiTools((prev) => ({ ...prev, [tool.id]: e.target.checked }))}
                    />
                    <span className="ai-tool-toggle-info">
                      <span className="ai-tool-toggle-name">{tool.label}</span>
                      <span className="ai-tool-toggle-desc">{tool.desc}</span>
                    </span>
                  </label>
                ))}
              </div>
              <p style={{ marginTop: 16, fontWeight: 600 }}>Services</p>
              <p style={{ fontSize: 12, marginTop: 8 }}>JupyterLab Port</p>
              <input type="number" value={jupyterPort} onChange={(e) => setJupyterPort(Number(e.target.value))} />
              <p style={{ fontSize: 12, marginTop: 8 }}>Model Proxy Port</p>
              <input type="number" value={modelProxyPort} onChange={(e) => setModelProxyPort(Number(e.target.value))} />

              <p style={{ marginTop: 16, fontWeight: 600 }}>Storage Paths</p>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, marginBottom: 6 }}>
                Configure where application data is stored. Changes take effect on next startup.
              </p>
              {([
                { label: 'Storage Dir', value: pathStorageDir, setter: setPathStorageDir },
                { label: 'Config Dir', value: pathConfigDir, setter: setPathConfigDir },
                { label: 'Artifacts Dir', value: pathArtifactsDir, setter: setPathArtifactsDir },
                { label: 'Slices Dir', value: pathSlicesDir, setter: setPathSlicesDir },
                { label: 'Notebooks Dir', value: pathNotebooksDir, setter: setPathNotebooksDir },
                { label: 'AI Tools Dir', value: pathAiToolsDir, setter: setPathAiToolsDir },
                { label: 'Token File', value: pathTokenFile, setter: setPathTokenFile },
                { label: 'Bastion Key', value: pathBastionKeyFile, setter: setPathBastionKeyFile },
                { label: 'Slice Keys Dir', value: pathSliceKeysDir, setter: setPathSliceKeysDir },
                { label: 'SSH Config', value: pathSshConfigFile, setter: setPathSshConfigFile },
                { label: 'Log File', value: pathLogFile, setter: setPathLogFile },
              ] as const).map((item) => (
                <div key={item.label} style={{ marginTop: 6 }}>
                  <p style={{ fontSize: 12, marginBottom: 2 }}>{item.label}</p>
                  <input type="text" value={item.value} onChange={(e) => item.setter(e.target.value)} style={{ fontSize: 12 }} />
                </div>
              ))}

              {/* Tool Configurations */}
              {toolConfigs.length > 0 && (
                <>
                  <p style={{ marginTop: 16, fontWeight: 600 }}>Tool Configurations</p>
                  <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2, marginBottom: 8 }}>
                    Per-tool configs are stored in .loomai/tools/. Reset replaces with Docker image defaults.
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {toolConfigs.map((tc) => (
                      <div key={tc.tool} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                        <span style={{ minWidth: 100 }}>{tc.tool}</span>
                        <span style={{ color: tc.has_config ? '#008e7a' : 'var(--text-muted)', fontSize: 12 }}>
                          {tc.has_config ? `${tc.files.length} files` : 'not configured'}
                        </span>
                        {tc.has_config && (
                          <button
                            className="btn-sm"
                            onClick={async () => {
                              try {
                                await api.resetToolConfig(tc.tool);
                                setMessage({ text: `Reset ${tc.tool} config to defaults`, type: 'success' });
                                loadToolConfigs();
                              } catch (err: any) {
                                setMessage({ text: `Reset failed: ${err.message}`, type: 'error' });
                              }
                            }}
                          >
                            Reset to Defaults
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Storage */}
        <div className="configure-section">
          <h3>Storage</h3>
          <p>Re-initialize storage directories. Use this if storage was corrupted.</p>
          <div className="btn-row">
            <button
              className="btn"
              onClick={async () => {
                setLoading(true);
                setMessage(null);
                try {
                  const result = await api.rebuildStorage();
                  setMessage({
                    text: `Storage rebuilt: ${result.slice_templates_total} slice templates, ${result.vm_templates_total} VM templates re-seeded.`,
                    type: 'success',
                  });
                } catch (err: any) {
                  setMessage({ text: `Rebuild failed: ${err.message}`, type: 'error' });
                } finally {
                  setLoading(false);
                }
              }}
              disabled={loading}
              data-help-id="settings.rebuild-storage"
              title="Re-initialize application storage"
            >
              {loading ? 'Rebuilding...' : 'Rebuild Storage'}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
