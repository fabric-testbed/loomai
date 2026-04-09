'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import * as api from '../api/client';
import type { ConfigStatus, ProjectInfo, SliceKeySet, LoomAISettings, ToolConfigStatus, UserInfo } from '../types/fabric';
import type { SettingTestResult } from '../api/client';
import '../styles/configure.css';

/* ---------- Section definitions ---------- */
type SectionId = 'profile' | 'ssh' | 'fablib' | 'projects' | 'llms' | 'ai-tools' | 'agents' | 'chameleon' | 'appearance' | 'storage';

interface SectionDef {
  id: SectionId;
  label: string;
  icon: string;
}

const SECTIONS: SectionDef[] = [
  { id: 'profile',    label: 'User Profile',  icon: '\u2302' },   // ⌂
  { id: 'ssh',        label: 'SSH Keys',       icon: '\u{1F511}' }, // key emoji fallback: 🔑
  { id: 'fablib',     label: 'FABlib',         icon: '\u2699' },   // ⚙
  { id: 'projects',   label: 'Projects',       icon: '\u25A3' },   // ▣
  { id: 'llms',       label: 'LLMs',           icon: '\u25C8' },   // ◈
  { id: 'ai-tools',   label: 'AI Tools',       icon: '\u2692' },   // ⚒
  { id: 'agents',     label: 'Agents & Skills', icon: '\u25C7' },   // ◇
  { id: 'chameleon',  label: 'Chameleon',       icon: '\u2766' },   // ❦
  { id: 'appearance', label: 'Appearance',      icon: '\u263C' },   // ☼
  { id: 'storage',    label: 'Storage',         icon: '\u25A8' },   // ▨
];

/* ---------- Component ---------- */
interface ConfigureViewProps {
  onConfigured: () => void;
  onClose?: () => void;
  hiddenProjects?: Set<string>;
  onHiddenProjectsChange?: (hidden: Set<string>) => void;
  /** Full project list from Core API (more complete than JWT-only list) */
  allProjects?: ProjectInfo[];
  /** Parent login handler — delegates OAuth flow to App.tsx so config/state stays in sync */
  onLogin?: () => void;
}

export default function ConfigureView({ onConfigured, onClose, hiddenProjects, onHiddenProjectsChange, allProjects, onLogin }: ConfigureViewProps) {
  const [activeSection, setActiveSection] = useState<SectionId>('profile');
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [bastionLogin, setBastionLogin] = useState('');
  const [selectedProject, setSelectedProject] = useState('');
  const [generatedPubKey, setGeneratedPubKey] = useState('');
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
    aider: true, opencode: true, crush: true, claude: false, deepagents: true,
  });

  // Multi-user state
  const [registeredUsers, setRegisteredUsers] = useState<UserInfo[]>([]);
  const [activeUserUuid, setActiveUserUuid] = useState<string | null>(null);
  const [switchingUser, setSwitchingUser] = useState(false);

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

  // AI model list (fetched from backend)
  const [aiModels, setAiModels] = useState<api.AIModelsResponse | null>(null);
  const [showKeyModal, setShowKeyModal] = useState<'fabric' | 'nrp' | null>(null);
  // Custom LLM providers
  const [customProviders, setCustomProviders] = useState<Array<{name: string; base_url: string; api_key: string}>>([]);

  // LLM key creation
  const [creatingLlmKey, setCreatingLlmKey] = useState(false);
  const [llmKeyMessage, setLlmKeyMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Views
  const [compositeViewEnabled, setCompositeViewEnabled] = useState(false);

  // Chameleon Cloud
  const [chameleonEnabled, setChameleonEnabled] = useState(false);
  const [chameleonSites, setChameleonSites] = useState<Record<string, { auth_url?: string; app_credential_id?: string; app_credential_secret?: string; project_id?: string }>>({});
  const [chameleonTestResults, setChameleonTestResults] = useState<Record<string, { ok: boolean; error: string; latency_ms: number }>>({});
  const [chameleonSshKey, setChameleonSshKey] = useState('');

  // Test results state
  const [testResults, setTestResults] = useState<Record<string, SettingTestResult | null>>({});
  const [testingKeys, setTestingKeys] = useState<Set<string>>(new Set());
  const [testAllResults, setTestAllResults] = useState<Record<string, SettingTestResult> | null>(null);
  const [testingAll, setTestingAll] = useState(false);

  // Agents & Skills
  const [agentsList, setAgentsList] = useState<api.AgentDetail[]>([]);
  const [skillsList, setSkillsList] = useState<api.SkillDetail[]>([]);
  const [editingAgent, setEditingAgent] = useState<api.AgentDetail | null>(null);
  const [editingSkill, setEditingSkill] = useState<api.SkillDetail | null>(null);
  const [agentForm, setAgentForm] = useState({ name: '', description: '', content: '' });
  const [skillForm, setSkillForm] = useState({ name: '', description: '', content: '' });
  const [creatingAgent, setCreatingAgent] = useState(false);
  const [creatingSkill, setCreatingSkill] = useState(false);

  const tokenFileRef = useRef<HTMLInputElement>(null);
  const bastionKeyRef = useRef<HTMLInputElement>(null);
  const slicePrivKeyRef = useRef<HTMLInputElement>(null);
  const slicePubKeyRef = useRef<HTMLInputElement>(null);

  /* ---------- Data loading ---------- */
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
      setCustomProviders(s.ai.custom_providers || []);
      // Views
      if (s.views) {
        setCompositeViewEnabled(s.views.composite_enabled || false);
      }
      // Chameleon
      if (s.chameleon) {
        setChameleonEnabled(s.chameleon.enabled || false);
        setChameleonSites(s.chameleon.sites || {});
        setChameleonSshKey(s.chameleon.ssh_key_file || '');
      }
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

  const loadUsers = useCallback(async () => {
    try {
      const data = await api.listUsers();
      setRegisteredUsers(data.users);
      setActiveUserUuid(data.active_user);
    } catch {
      // ignore — may not have users endpoint yet
    }
  }, []);

  const loadModels = useCallback(async () => {
    try { setAiModels(await api.getAiModels()); } catch { /* ignore */ }
  }, []);

  const loadAgents = useCallback(async () => {
    try { setAgentsList(await api.getAgents()); } catch { /* ignore */ }
  }, []);

  const loadSkills = useCallback(async () => {
    try { setSkillsList(await api.getSkills()); } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadStatus();
    loadKeySets();
    loadSettings();
    loadToolConfigs();
    loadUsers();
    loadModels();
    loadAgents();
    loadSkills();
  }, [loadStatus, loadKeySets, loadSettings, loadToolConfigs, loadUsers, loadModels, loadAgents, loadSkills]);

  // Load projects when token is available
  const loadProjects = useCallback(async () => {
    try {
      const data = await api.getProjects();
      setProjects(data.projects);
      if (data.bastion_login) setBastionLogin(data.bastion_login);
      // Only default to first project if no project is already set from settings
      if (data.projects.length > 0) {
        setSelectedProject((prev) => prev || data.projects[0].uuid);
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

  /* ---------- Handlers ---------- */
  const handleTokenUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      await api.uploadToken(file);
      setMessage({ text: 'Token uploaded successfully', type: 'success' });
      await Promise.all([loadStatus(), loadUsers(), loadSettings(), loadKeySets()]);
      await loadProjects();
    } catch (err: any) {
      setMessage({ text: `Token upload failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
      if (tokenFileRef.current) tokenFileRef.current.value = '';
    }
  };

  const handleOAuthLogin = () => {
    if (onLogin) {
      // Delegate to App.tsx which handles token polling, auto-setup,
      // config state updates, and closing the settings panel.
      onLogin();
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
      await Promise.all([loadStatus(), loadUsers(), loadSettings(), loadKeySets()]);
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
          custom_providers: customProviders,
          tools: aiTools,
        },
        chameleon: {
          enabled: chameleonEnabled,
          default_site: settings?.chameleon?.default_site || 'CHI@TACC',
          ssh_key_file: chameleonSshKey,
          sites: chameleonSites,
        },
        services: {
          jupyter_port: jupyterPort,
          model_proxy_port: modelProxyPort,
        },
        tool_configs: settings?.tool_configs ?? {},
        views: {
          composite_enabled: compositeViewEnabled,
        },
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

  /* ---------- Test helpers ---------- */
  const runTest = async (key: string) => {
    setTestingKeys((prev) => new Set(prev).add(key));
    setTestResults((prev) => ({ ...prev, [key]: null }));
    try {
      const result = await api.testSetting(key);
      setTestResults((prev) => ({ ...prev, [key]: result }));
    } catch (err: any) {
      setTestResults((prev) => ({ ...prev, [key]: { ok: false, message: err.message } }));
    } finally {
      setTestingKeys((prev) => { const n = new Set(prev); n.delete(key); return n; });
    }
  };

  const runTestAll = async () => {
    setTestingAll(true);
    setTestAllResults(null);
    try {
      const results = await api.testAllSettings();
      setTestAllResults(results);
    } catch {
      setTestAllResults({});
    } finally {
      setTestingAll(false);
    }
  };

  const TestButton = ({ testKey, label }: { testKey: string; label?: string }) => {
    const isTesting = testingKeys.has(testKey);
    const result = testResults[testKey];
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <button
          className={`test-btn${isTesting ? ' testing' : ''}`}
          onClick={() => runTest(testKey)}
          disabled={isTesting}
        >
          {isTesting && <span className="test-spinner" />}
          {label || 'Test'}
        </button>
        {result && (
          <span className={`test-result ${result.ok ? 'test-ok' : 'test-fail'}`}>
            {result.ok ? '\u2713' : '\u2717'} {result.message}
            {result.latency_ms != null && <span className="test-latency"> ({result.latency_ms}ms)</span>}
          </span>
        )}
      </span>
    );
  };

  const tokenExpiry = status?.token_info?.exp
    ? new Date(status.token_info.exp * 1000).toLocaleString()
    : null;

  const effectiveKeyName = showAddKeySet && newKeyName.trim() ? newKeyName.trim() : 'default';

  /* ---------- Section renderers ---------- */

  const renderProfile = () => (
    <>
      {/* User Accounts — only show when 2+ users registered */}
      {registeredUsers.length >= 2 && (
        <div className="configure-section">
          <h3>User Accounts</h3>
          <p>Switch between registered FABRIC identities. To add a new user, upload or paste their token below.</p>
          <div className="user-account-list">
            {registeredUsers.map((u) => (
              <div
                key={u.uuid}
                className={`user-account-row${u.is_active ? ' active' : ''}`}
              >
                <div className="user-account-info">
                  <span className="user-account-name">{u.name || 'Unknown'}</span>
                  <span className="user-account-email">{u.email}</span>
                  <span className="user-account-uuid">{u.uuid.slice(0, 8)}...</span>
                </div>
                <div className="user-account-actions">
                  {u.is_active ? (
                    <span className="user-account-active-badge">Active</span>
                  ) : (
                    <>
                      <button
                        className="btn primary btn-sm"
                        disabled={switchingUser}
                        onClick={async () => {
                          setSwitchingUser(true);
                          try {
                            await api.switchUser(u.uuid);
                            setMessage({ text: `Switched to ${u.name || u.email}`, type: 'success' });
                            await Promise.all([loadStatus(), loadUsers(), loadSettings(), loadKeySets()]);
                            await loadProjects();
                          } catch (err: any) {
                            setMessage({ text: `Switch failed: ${err.message}`, type: 'error' });
                          } finally {
                            setSwitchingUser(false);
                          }
                        }}
                      >
                        {switchingUser ? 'Switching...' : 'Switch'}
                      </button>
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={async () => {
                          if (!confirm(`Remove ${u.name || u.email}? This will unregister the user. Their data will remain on disk.`)) return;
                          try {
                            await api.removeUser(u.uuid);
                            setMessage({ text: `Removed ${u.name || u.email}`, type: 'success' });
                            await loadUsers();
                          } catch (err: any) {
                            setMessage({ text: `Remove failed: ${err.message}`, type: 'error' });
                          }
                        }}
                      >
                        Remove
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Token upload */}
      <div className="configure-section" data-tour-id="token">
        <div className="section-heading-row">
          <h3>FABRIC Token</h3>
          <div className="test-inline">
            <TestButton testKey="token" label="Test Token" />
          </div>
        </div>
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
      </div>

      {/* Bastion Username */}
      <div className="configure-section">
        <h3>Bastion Username</h3>
        <p>Your FABRIC bastion login username (auto-detected from token when possible).</p>
        <input
          type="text"
          value={bastionLogin}
          onChange={(e) => setBastionLogin(e.target.value)}
          placeholder="e.g. user_name_0001234567"
          title="Your FABRIC bastion login (auto-detected from token)"
        />
      </div>
    </>
  );

  const renderSSHKeys = () => (
    <>
      {/* Bastion Key */}
      <div className="configure-section" data-tour-id="bastion-key">
        <div className="section-heading-row">
          <h3>Bastion Key</h3>
          <div className="test-inline">
            <TestButton testKey="bastion_ssh" label="Test Bastion SSH" />
          </div>
        </div>
        <p>Upload your FABRIC bastion private key (from the portal).</p>
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
          <button
            className="btn"
            onClick={async () => {
              if (status?.has_bastion_key && !confirm('Regenerate bastion key? This will replace the existing key.')) return;
              setLoading(true);
              try {
                const res = await api.generateBastionKey(!!status?.has_bastion_key);
                if (res.generated) {
                  setMessage({ text: 'Bastion key generated successfully', type: 'success' });
                  loadStatus();
                } else {
                  setMessage({ text: 'Bastion key already exists. Use Regenerate to replace it.', type: 'error' });
                }
              } catch (e: any) {
                setMessage({ text: `Key generation failed: ${e.message}`, type: 'error' });
              } finally {
                setLoading(false);
              }
            }}
            disabled={loading || !status?.has_token}
          >
            {status?.has_bastion_key ? 'Regenerate Key' : 'Generate Key'}
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
      </div>

      {/* Slice Key Sets */}
      <div className="configure-section" data-tour-id="slice-keys">
        <h3>Slice Key Sets</h3>
        <p>Manage named SSH key pairs for slice access.</p>

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
    </>
  );

  const renderFABlib = () => (
    <>
      <div className="configure-section">
        <div className="section-heading-row">
          <h3>FABRIC Hosts</h3>
          <div className="test-inline">
            <TestButton testKey="fablib" label="Test FABlib" />
          </div>
        </div>
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
      </div>

      <div className="configure-section">
        <h3>Logging</h3>
        <p>Log Level</p>
        <select value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
          <option>DEBUG</option>
          <option>INFO</option>
          <option>WARNING</option>
          <option>ERROR</option>
        </select>
        <p>Log File</p>
        <input type="text" value={logFile} onChange={(e) => setLogFile(e.target.value)} />
      </div>

      <div className="configure-section">
        <h3>SSH Command Line</h3>
        <p>Template used when opening SSH connections to slice nodes.</p>
        <input type="text" value={sshCommandLine} onChange={(e) => setSshCommandLine(e.target.value)} />
      </div>

      <div className="configure-section">
        <h3 data-help-id="settings.avoid-sites">Sites to Avoid</h3>
        <p>Click a site to toggle it. Avoided sites will not be used for auto-placement.</p>
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
      </div>
    </>
  );

  const renderProjects = () => {
    const isService = (p: { name: string }) => /^SERVICE\s*[-–—]/i.test(p.name);
    const allProjList = allProjects && allProjects.length > 0 ? allProjects : projects;
    const allRegular = allProjList.filter(p => !isService(p));
    const allService = allProjList.filter(p => isService(p));

    return (
    <>
      <div className="configure-section">
        <div className="section-heading-row">
          <h3 data-help-id="settings.project">Projects</h3>
          <div className="test-inline">
            <TestButton testKey="project" label="Test Project" />
          </div>
        </div>
        <p>Click a project to make it active. Use the eye toggle to show or hide it in the project switcher.</p>
        {allRegular.length === 0 && status?.has_token && (
          <p style={{ color: 'var(--fabric-text-muted)', fontStyle: 'italic' }}>Loading projects...</p>
        )}
        {allRegular.length === 0 && !status?.has_token && (
          <p style={{ color: 'var(--fabric-text-muted)', fontStyle: 'italic' }}>Login to load your projects.</p>
        )}
        <div className="project-toggle-list">
          {allRegular.map((p) => {
            const isHidden = hiddenProjects?.has(p.uuid) ?? false;
            const isActive = p.uuid === selectedProject;
            return (
              <div
                key={p.uuid}
                className={`project-toggle-row${isActive ? ' project-active-row' : ''}${isHidden ? ' hidden-project' : ''}`}
                onClick={() => setSelectedProject(p.uuid)}
                style={{ cursor: 'pointer' }}
              >
                {onHiddenProjectsChange && allRegular.length > 1 && (
                  <button
                    className={`project-visibility-btn${isHidden ? ' project-hidden' : ''}`}
                    title={isActive ? 'Active project is always visible' : isHidden ? 'Show in switcher' : 'Hide from switcher'}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (isActive) return;
                      const next = new Set(hiddenProjects);
                      if (isHidden) next.delete(p.uuid);
                      else next.add(p.uuid);
                      onHiddenProjectsChange(next);
                    }}
                    disabled={isActive}
                  >
                    {isHidden ? '\u{1F441}\u{200D}\u{1F5E8}' : '\u{1F441}'}
                  </button>
                )}
                <span className="project-toggle-name">{p.name}</span>
                {isActive && <span className="project-toggle-active">active</span>}
              </div>
            );
          })}
        </div>
      </div>

      {/* Service Projects — read-only membership list */}
      {allService.length > 0 && (
        <div className="configure-section">
          <h3>Service Projects</h3>
          <p style={{ fontSize: 12, color: 'var(--fabric-text-muted)', marginBottom: 8 }}>
            Service projects are for infrastructure services only. Slices cannot be provisioned under these projects.
          </p>
          <div className="project-toggle-list">
            {allService.map((p) => (
              <div key={p.uuid} className="project-toggle-row" style={{ opacity: 0.65, cursor: 'default' }}>
                <span className="project-toggle-name">{p.name}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
    );
  };

  const renderLLMs = () => (
    <>
      <div className="configure-section" data-tour-id="ai-api-key">
        <h3>API Keys</h3>
        <p data-help-id="settings.ai-api-key">
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
          <button
            disabled={creatingLlmKey || !status?.has_token || (status?.ai_api_key_set && !litellmApiKey) || !(allProjects || []).some(p => /^SERVICE\s*[-\u2013\u2014].*LLM/i.test(p.name))}
            onClick={async () => {
              setCreatingLlmKey(true);
              setLlmKeyMessage(null);
              try {
                const result = await api.createLlmKey();
                setLlmKeyMessage({ text: result.message, type: 'success' });
                // Refresh config status to update the "Configured" badge
                const cfg = await api.getConfig();
                setStatus(cfg);
              } catch (err: any) {
                setLlmKeyMessage({ text: err.message || 'Failed to create LLM key', type: 'error' });
              } finally {
                setCreatingLlmKey(false);
              }
            }}
            title={
              !status?.has_token ? 'Login first to create an LLM key' :
              (status?.ai_api_key_set && !litellmApiKey) ? 'FABRIC AI key already configured' :
              !(allProjects || []).some(p => /^SERVICE\s*[-\u2013\u2014].*LLM/i.test(p.name)) ? 'Requires membership in a SERVICE LLM project' :
              'Create or retrieve a FABRIC LLM API key'
            }
            style={{ whiteSpace: 'nowrap', fontSize: 11, padding: '4px 8px' }}
          >
            {creatingLlmKey ? 'Creating...' : 'Create FABRIC LLM Token'}
          </button>
        </div>
        {llmKeyMessage && (
          <p style={{ fontSize: 11, marginTop: 4, color: llmKeyMessage.type === 'success' ? '#008e7a' : '#e25241' }}>
            {llmKeyMessage.text}
          </p>
        )}

        <p style={{ marginTop: 10 }} data-help-id="settings.nrp-api-key">
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
          <a
            href="https://nrp.ai/llmtoken/"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              whiteSpace: 'nowrap', fontSize: 11, padding: '4px 8px',
              background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
              borderRadius: 4, color: 'var(--text-color)', textDecoration: 'none',
              cursor: 'pointer', display: 'inline-block',
            }}
          >
            Get NRP Token {'\u2197'}
          </a>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <TestButton testKey="ai_server" label="Test FABRIC AI" />
          <TestButton testKey="nrp_server" label="Test NRP" />
        </div>
      </div>

      <div className="configure-section">
        <h3>Server URLs</h3>
        <p>Server endpoints for AI model access.</p>
        <p style={{ fontSize: 12, marginTop: 8 }}>FABRIC AI Server URL</p>
        <input type="text" value={aiServerUrl} onChange={(e) => setAiServerUrl(e.target.value)} />
        <p style={{ fontSize: 12, marginTop: 8 }}>NRP Server URL</p>
        <input type="text" value={nrpServerUrl} onChange={(e) => setNrpServerUrl(e.target.value)} />
      </div>

      <div className="configure-section">
        <h3>Available LLM Models</h3>
        <p>
          Models available from FABRIC AI and NRP servers. All FABRIC testbed users are eligible for a free API key.
        </p>
        {aiModels && (
          <div style={{ fontSize: 12, marginTop: 4 }}>
            {aiModels.fabric.length > 0 && (
              <>
                <p style={{ fontWeight: 600, color: 'var(--fabric-primary)', marginTop: 8 }}>FABRIC AI Models {!aiModels.has_key.fabric && <span style={{ color: 'var(--text-muted)' }}>(API key required)</span>}</p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {aiModels.fabric.map(m => (
                    <span key={m.id} style={{
                      padding: '2px 8px', borderRadius: 4,
                      background: m.healthy === false ? 'var(--bg-error, #fce4ec)' : 'var(--bg-secondary)',
                      border: `1px solid ${m.healthy === false ? 'var(--error-color, #b00020)' : 'var(--border-color)'}`,
                      opacity: m.healthy === false ? 0.6 : 1,
                      textDecoration: m.healthy === false ? 'line-through' : 'none',
                    }}>
                      {m.name}{m.healthy === false ? ' (unavailable)' : ''}
                    </span>
                  ))}
                </div>
              </>
            )}
            {aiModels.nrp.length > 0 && (
              <>
                <p style={{ fontWeight: 600, color: 'var(--fabric-teal)', marginTop: 8 }}>NRP/Nautilus Models {!aiModels.has_key.nrp && <span style={{ color: 'var(--text-muted)' }}>(API key required)</span>}</p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {aiModels.nrp.map(m => (
                    <span key={m.id} style={{
                      padding: '2px 8px', borderRadius: 4,
                      background: m.healthy === false ? 'var(--bg-error, #fce4ec)' : 'var(--bg-secondary)',
                      border: `1px solid ${m.healthy === false ? 'var(--error-color, #b00020)' : 'var(--border-color)'}`,
                      opacity: m.healthy === false ? 0.6 : 1,
                      textDecoration: m.healthy === false ? 'line-through' : 'none',
                    }}>
                      {m.name}{m.healthy === false ? ' (unavailable)' : ''}
                    </span>
                  ))}
                </div>
              </>
            )}
            {aiModels.fabric.length === 0 && aiModels.nrp.length === 0 && (
              <p style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                No models available. Configure your FABRIC AI API key above to see available models.
              </p>
            )}
            {(!aiModels.has_key.fabric || !aiModels.has_key.nrp) && (
              <p style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                {!aiModels.has_key.fabric && <>Missing FABRIC API key — all FABRIC testbed users are eligible. Enter your key in the API Keys section above. </>}
                {!aiModels.has_key.nrp && <>Missing NRP API key — enter it in the API Keys section above for additional models.</>}
              </p>
            )}
            {aiModels.default && (
              <p style={{ marginTop: 6, fontSize: 11 }}>Default model: <strong>{aiModels.default}</strong></p>
            )}
          </div>
        )}
      </div>

      <div className="configure-section">
        <h3>Custom LLM Providers</h3>
        <p>Add custom OpenAI-compatible LLM providers (Ollama, vLLM, etc.).</p>
        {customProviders.map((cp, i) => (
          <div key={i} style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
            <input type="text" placeholder="Name" value={cp.name} style={{ width: 80, fontSize: 12 }}
              onChange={e => { const next = [...customProviders]; next[i] = { ...cp, name: e.target.value }; setCustomProviders(next); }} />
            <input type="text" placeholder="Base URL" value={cp.base_url} style={{ flex: 1, fontSize: 12 }}
              onChange={e => { const next = [...customProviders]; next[i] = { ...cp, base_url: e.target.value }; setCustomProviders(next); }} />
            <input type="password" placeholder="API Key" value={cp.api_key} style={{ width: 120, fontSize: 12 }}
              onChange={e => { const next = [...customProviders]; next[i] = { ...cp, api_key: e.target.value }; setCustomProviders(next); }} />
            <button style={{ fontSize: 11, padding: '2px 6px', cursor: 'pointer', border: '1px solid var(--fabric-border)', borderRadius: 3, background: 'var(--fabric-bg-tint)', color: 'var(--fabric-text-muted)' }}
              onClick={() => setCustomProviders(customProviders.filter((_, j) => j !== i))}>X</button>
          </div>
        ))}
        <button className="btn" style={{ marginTop: 6, fontSize: 12, padding: '4px 12px' }}
          onClick={() => setCustomProviders([...customProviders, { name: '', base_url: '', api_key: '' }])}>
          + Add Provider
        </button>
      </div>

      <div className="configure-section">
        <h3>Model Proxy</h3>
        <p>Local model proxy port for tools with hardcoded model references.</p>
        <p style={{ fontSize: 12 }}>Model Proxy Port</p>
        <input type="number" value={modelProxyPort} onChange={(e) => setModelProxyPort(Number(e.target.value))} />
      </div>
    </>
  );

  const renderAITools = () => (
    <>
      <div className="configure-section">
        <h3 data-help-id="settings.ai-tools">Enabled Tools</h3>
        <p>Choose which AI tools appear in the AI Companion launcher.</p>
        <div className="ai-tool-toggles">
          {([
            { id: 'aider', label: 'Aider', desc: 'AI pair programming terminal' },
            { id: 'opencode', label: 'OpenCode', desc: 'Terminal-based AI coding assistant' },
            { id: 'crush', label: 'Crush', desc: 'Terminal AI assistant (Charm)' },
            { id: 'deepagents', label: 'Deep Agents', desc: 'LangChain coding agent with planning and memory' },
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
      </div>

      <div className="configure-section">
        <h3>Services</h3>
        <p style={{ fontSize: 12 }}>JupyterLab Port</p>
        <input type="number" value={jupyterPort} onChange={(e) => setJupyterPort(Number(e.target.value))} />
      </div>

      {/* Tool Configurations */}
      {toolConfigs.length > 0 && (
        <div className="configure-section">
          <h3>Tool Configurations</h3>
          <p>Per-tool configs are stored in .loomai/tools/. Reset replaces with Docker image defaults.</p>
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
        </div>
      )}
    </>
  );

  const renderChameleon = () => (
    <div className="configure-section">
      <h3>Chameleon Cloud</h3>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
        <label style={{ fontSize: 12, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={chameleonEnabled}
            onChange={e => setChameleonEnabled(e.target.checked)}
            style={{ marginRight: 4 }}
          />
          Enable Chameleon Cloud Integration
        </label>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
        <label style={{ fontSize: 12, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={compositeViewEnabled}
            onChange={e => setCompositeViewEnabled(e.target.checked)}
            style={{ marginRight: 4 }}
          />
          Enable Composite Slices View
        </label>
        <span style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>(cross-testbed experiments)</span>
      </div>
      {chameleonEnabled && (
        <div style={{ marginTop: 8 }}>
          <p>
            Enter application credentials for each Chameleon site. Create them at each site's dashboard under Identity &rarr; Application Credentials.
          </p>
          {Object.entries(chameleonSites).map(([siteName, siteCfg]) => (
            <div key={siteName} style={{ marginTop: 8, padding: 8, border: '1px solid var(--fabric-border)', borderRadius: 6 }}>
              <p style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>{siteName}</p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <input type="text" placeholder="App Credential ID" value={siteCfg.app_credential_id || ''}
                  onChange={e => setChameleonSites(prev => ({ ...prev, [siteName]: { ...prev[siteName], app_credential_id: e.target.value } }))}
                  style={{ fontSize: 11 }} />
                <input type="password" placeholder="App Credential Secret" value={siteCfg.app_credential_secret || ''}
                  onChange={e => setChameleonSites(prev => ({ ...prev, [siteName]: { ...prev[siteName], app_credential_secret: e.target.value } }))}
                  style={{ fontSize: 11 }} />
              </div>
              <input type="text" placeholder="Project ID" value={siteCfg.project_id || ''}
                onChange={e => setChameleonSites(prev => ({ ...prev, [siteName]: { ...prev[siteName], project_id: e.target.value } }))}
                style={{ fontSize: 11, marginTop: 4, width: '100%' }} />
              <button
                className="test-btn"
                style={{ marginTop: 4 }}
                onClick={async () => {
                  setChameleonTestResults(prev => ({ ...prev, [siteName]: { ok: false, error: 'Testing...', latency_ms: 0 } }));
                  try {
                    const r = await api.testChameleonConnection(siteName);
                    setChameleonTestResults(prev => ({ ...prev, ...r }));
                  } catch (e: any) {
                    setChameleonTestResults(prev => ({ ...prev, [siteName]: { ok: false, error: e.message, latency_ms: 0 } }));
                  }
                }}
              >Test Connection</button>
              {chameleonTestResults[siteName] && (
                <span style={{ fontSize: 11, marginLeft: 8, color: chameleonTestResults[siteName].ok ? 'green' : 'var(--text-muted)' }}>
                  {chameleonTestResults[siteName].ok
                    ? `\u2713 Connected (${chameleonTestResults[siteName].latency_ms}ms)`
                    : chameleonTestResults[siteName].error}
                </span>
              )}
            </div>
          ))}
          <div style={{ marginTop: 12 }}>
            <p style={{ fontWeight: 600, marginBottom: 3 }}>SSH Key (optional)</p>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
              Path to SSH private key for Chameleon instances. Leave empty to use the FABRIC slice key.
            </p>
            <input type="text" placeholder="/home/fabric/work/fabric_config/chameleon_key" value={chameleonSshKey}
              onChange={e => setChameleonSshKey(e.target.value)}
              style={{ fontSize: 11, width: '100%' }} />
          </div>
        </div>
      )}
    </div>
  );

  const renderAppearance = () => (
    <>
      <div className="configure-section">
        <h3 data-help-id="settings.tour">Getting Started Tour</h3>
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
      </div>
    </>
  );

  const renderAgentsAndSkills = () => {
    const renderForm = (
      type: 'agent' | 'skill',
      existing: (api.AgentDetail | api.SkillDetail) | null,
      form: { name: string; description: string; content: string },
      setForm: (v: { name: string; description: string; content: string }) => void,
      onSave: () => void,
      onCancel: () => void,
    ) => (
      <div style={{ background: 'var(--bg-secondary, #1a1a2e)', padding: 12, borderRadius: 6, marginBottom: 8 }}>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>Name</label>
            <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder={type === 'agent' ? 'e.g. My Custom Agent' : 'e.g. deploy-aws'}
              style={{ width: '100%' }} />
          </div>
          <div style={{ flex: 2 }}>
            <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>Description</label>
            <input value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="Brief description of what this does"
              style={{ width: '100%' }} />
          </div>
        </div>
        <div>
          <label style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {type === 'agent' ? 'Agent Prompt (Markdown)' : 'Skill Instructions (Markdown)'}
          </label>
          <textarea value={form.content} onChange={e => setForm({ ...form, content: e.target.value })}
            style={{ width: '100%', minHeight: 300, fontFamily: 'monospace', fontSize: 12 }}
            placeholder={type === 'agent'
              ? 'You are a specialized agent that...\n\n## Your Capabilities\n- ...'
              : 'Instructions for this skill...\n\n## Steps\n1. ...'} />
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button className="btn btn-primary" onClick={onSave}>Save</button>
          <button className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    );

    const renderItemList = (
      items: (api.AgentDetail | api.SkillDetail)[],
      type: 'agent' | 'skill',
      editing: api.AgentDetail | api.SkillDetail | null,
      setEditing: (v: api.AgentDetail | api.SkillDetail | null) => void,
      form: { name: string; description: string; content: string },
      setForm: (v: { name: string; description: string; content: string }) => void,
      creating: boolean,
      setCreating: (v: boolean) => void,
      loadFn: () => void,
    ) => (
      <div className="configure-section">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3>{type === 'agent' ? 'Agents' : 'Skills'}</h3>
          <button className="btn-sm" onClick={() => {
            setCreating(true);
            setEditing(null);
            setForm({ name: '', description: '', content: '' });
          }}>+ New {type === 'agent' ? 'Agent' : 'Skill'}</button>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
          {type === 'agent'
            ? 'Agent personas define how the LoomAI assistant behaves. Select an agent in the assistant panel to activate it.'
            : 'Skills are instruction sets that AI tools can use. They appear as slash commands in compatible tools.'}
        </p>

        {creating && renderForm(type, null, form, setForm, async () => {
          const id = form.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
          if (!id) { setMessage({ text: 'Name is required', type: 'error' }); return; }
          try {
            const saveFn = type === 'agent' ? api.saveAgent : api.saveSkill;
            await saveFn(id, form);
            setCreating(false);
            setMessage({ text: `${type === 'agent' ? 'Agent' : 'Skill'} created`, type: 'success' });
            loadFn();
          } catch (err: any) {
            setMessage({ text: `Save failed: ${err.message}`, type: 'error' });
          }
        }, () => setCreating(false))}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {items.map(item => (
            <div key={item.id}>
              {editing?.id === item.id ? (
                renderForm(type, item, form, setForm, async () => {
                  try {
                    const saveFn = type === 'agent' ? api.saveAgent : api.saveSkill;
                    await saveFn(item.id, form);
                    setEditing(null);
                    setMessage({ text: 'Saved', type: 'success' });
                    loadFn();
                  } catch (err: any) {
                    setMessage({ text: `Save failed: ${err.message}`, type: 'error' });
                  }
                }, () => setEditing(null))
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border-color, #333)' }}>
                  <span style={{ fontWeight: 500, minWidth: 140, fontSize: 13 }}>{item.name || item.id}</span>
                  <span style={{ flex: 1, fontSize: 12, color: 'var(--text-muted)' }}>{item.description}</span>
                  <span style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 3,
                    background: item.source === 'built-in' ? '#333' : item.source === 'custom' ? '#008e7a22' : '#ff854222',
                    color: item.source === 'built-in' ? '#999' : item.source === 'custom' ? '#008e7a' : '#ff8542',
                  }}>{item.source}</span>
                  <button className="btn-sm" onClick={async () => {
                    try {
                      const getFn = type === 'agent' ? api.getAgent : api.getSkill;
                      const full = await getFn(item.id);
                      setEditing(full);
                      setCreating(false);
                      setForm({ name: full.name, description: full.description, content: full.content || '' });
                    } catch (err: any) {
                      setMessage({ text: `Load failed: ${err.message}`, type: 'error' });
                    }
                  }}>Edit</button>
                  {item.source === 'customized' && (
                    <button className="btn-sm" onClick={async () => {
                      try {
                        const resetFn = type === 'agent' ? api.resetAgent : api.resetSkill;
                        await resetFn(item.id);
                        setMessage({ text: 'Reset to default', type: 'success' });
                        loadFn();
                      } catch (err: any) {
                        setMessage({ text: `Reset failed: ${err.message}`, type: 'error' });
                      }
                    }}>Reset</button>
                  )}
                  {item.source !== 'built-in' && (
                    <button className="btn-sm btn-danger" onClick={async () => {
                      if (!confirm(`Delete ${type} "${item.name}"?`)) return;
                      try {
                        const delFn = type === 'agent' ? api.deleteAgent : api.deleteSkill;
                        await delFn(item.id);
                        setMessage({ text: 'Deleted', type: 'success' });
                        loadFn();
                      } catch (err: any) {
                        setMessage({ text: `Delete failed: ${err.message}`, type: 'error' });
                      }
                    }}>Delete</button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );

    return (
      <>
        {renderItemList(agentsList, 'agent', editingAgent, setEditingAgent, agentForm, setAgentForm, creatingAgent, setCreatingAgent, loadAgents)}
        {renderItemList(skillsList, 'skill', editingSkill, setEditingSkill, skillForm, setSkillForm, creatingSkill, setCreatingSkill, loadSkills)}
      </>
    );
  };

  const renderStorage = () => (
    <>
      <div className="configure-section">
        <h3>Storage Paths</h3>
        <p>Configure where application data is stored. Changes take effect on next startup.</p>
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
      </div>

      <div className="configure-section">
        <h3>Rebuild Storage</h3>
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
                  text: `Storage rebuilt: ${result.directories_created} directories initialized.`,
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
    </>
  );

  /* ---------- Section routing ---------- */
  const renderActiveSection = () => {
    switch (activeSection) {
      case 'profile':    return renderProfile();
      case 'ssh':        return renderSSHKeys();
      case 'fablib':     return renderFABlib();
      case 'projects':   return renderProjects();
      case 'llms':       return renderLLMs();
      case 'ai-tools':   return renderAITools();
      case 'agents':     return renderAgentsAndSkills();
      case 'chameleon':  return renderChameleon();
      case 'appearance': return renderAppearance();
      case 'storage':    return renderStorage();
      default:           return renderProfile();
    }
  };

  /* ---------- Render ---------- */
  return (
    <div className="configure-view">
      {/* Top bar with title, save & close */}
      <div className="configure-topbar" data-tour-id="save-close">
        <div className="configure-topbar-left">
          <h2 className="configure-title">{'\u2699'} Settings</h2>
          {/* Status dots */}
          <div className="status-banner" style={{ margin: 0, padding: '6px 12px', border: 'none', background: 'transparent' }}>
            <div className="status-item">
              <span className={`status-dot ${status?.has_token ? 'ok' : 'missing'}`} />
              Token
            </div>
            <div className="status-item">
              <span className={`status-dot ${status?.has_bastion_key ? 'ok' : 'missing'}`} />
              Bastion
            </div>
            <div className="status-item">
              <span className={`status-dot ${status?.has_slice_key ? 'ok' : 'missing'}`} />
              Keys
            </div>
            <div className="status-item">
              <span className={`status-dot ${selectedProject ? 'ok' : 'missing'}`} />
              Project
            </div>
          </div>
        </div>
        <div className="configure-topbar-actions">
          <button
            className="btn primary"
            onClick={handleSave}
            disabled={saving || !status?.has_token || !selectedProject || !bastionLogin}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          {onClose && (
            <button className="btn configure-close-btn" onClick={onClose}>
              Close
            </button>
          )}
        </div>
      </div>

      {/* Mobile dropdown (< 768px) */}
      <div className="configure-mobile-nav">
        <select
          value={activeSection}
          onChange={(e) => setActiveSection(e.target.value as SectionId)}
        >
          {SECTIONS.map((s) => (
            <option key={s.id} value={s.id}>{s.icon} {s.label}</option>
          ))}
        </select>
      </div>

      {/* Two-panel layout */}
      <div className="configure-layout">
        {/* Sidebar */}
        <div className="configure-sidebar">
          <div className="configure-sidebar-nav">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                className={`configure-sidebar-item${activeSection === s.id ? ' active' : ''}`}
                onClick={() => setActiveSection(s.id)}
              >
                <span className="configure-sidebar-icon">{s.icon}</span>
                {s.label}
              </button>
            ))}
          </div>
          <div className="configure-sidebar-header">
            <button
              className={`test-btn test-btn-all${testingAll ? ' testing' : ''}`}
              onClick={runTestAll}
              disabled={testingAll}
            >
              {testingAll && <span className="test-spinner" />}
              {testingAll ? 'Testing...' : 'Test All'}
            </button>
            {testAllResults && (
              <div className="test-all-results">
                {Object.entries(testAllResults).map(([key, result]) => (
                  <div key={key} className="test-all-row">
                    <span className="test-all-label">{key}</span>
                    <span className={`test-result ${result.ok ? 'test-ok' : 'test-fail'}`}>
                      {result.ok ? '\u2713' : '\u2717'} {result.message}
                      {result.latency_ms != null && <span className="test-latency"> ({result.latency_ms}ms)</span>}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="configure-content">
          <div className="configure-content-inner">
            {/* Global message */}
            {message && (
              <div className={`configure-message ${message.type}`}>
                {message.text}
              </div>
            )}
            {renderActiveSection()}
          </div>
        </div>
      </div>
    </div>
  );
}
