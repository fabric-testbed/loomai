'use client';
import InAppSelect from './InAppSelect';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import * as api from '../api/client';
import type { ConfigStatus, ProjectInfo, SliceKeySet, LoomAISettings, ToolConfigStatus, UserInfo } from '../types/fabric';
import type { SettingTestResult, ToolInstallInfo } from '../api/client';
import ToolInstallOverlay from './ToolInstallOverlay';
import { confirmDialog } from './AppDialogProvider';
import '../styles/configure.css';

/* ---------- Section definitions ---------- */
type SectionId = 'profile' | 'ssh' | 'fablib' | 'projects' | 'llms' | 'ai-tools' | 'agents' | 'chameleon' | 'appearance' | 'storage';

interface SectionDef {
  id: SectionId;
  label: string;
  icon: string;
}

type ChameleonAuthType = 'application_credential' | 'password';
type ChameleonKeypair = {
  name?: string;
  fingerprint?: string;
  type?: string;
  _site?: string;
  has_private_key?: boolean;
  private_key_path?: string;
};
type ChameleonSiteSettings = {
  auth_type?: ChameleonAuthType;
  auth_url?: string;
  default_key_name?: string;
  app_credential_id?: string;
  app_credential_secret?: string;
  project_id?: string;
  project_name?: string;
  project_domain_name?: string;
  identity_provider?: string;
  protocol?: string;
  discovery_endpoint?: string;
  client_id?: string;
  client_secret?: string;
  access_token_type?: string;
  openid_scope?: string;
};

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

function serializeChameleonSitesForDirty(sites?: Record<string, ChameleonSiteSettings | Record<string, unknown>>): string {
  const normalized = Object.fromEntries(
    Object.entries(sites || {})
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([siteName, siteCfg]) => {
        const { username: _legacyUsername, password: _legacyPassword, ...siteWithoutPassword } = siteCfg as Record<string, unknown>;
        const sortedSite = Object.fromEntries(
          Object.entries(siteWithoutPassword).sort(([a], [b]) => a.localeCompare(b)),
        );
        return [siteName, sortedSite];
      }),
  );
  return JSON.stringify(normalized);
}

/* ---------- Component ---------- */
interface ConfigureViewProps {
  onConfigured: () => void;
  onClose?: () => void;
  hiddenProjects?: Set<string>;
  onHiddenProjectsChange?: (hidden: Set<string>) => void;
  /** Full project list from Core API (more complete than JWT-only list) */
  allProjects?: ProjectInfo[];
}

export default function ConfigureView({ onConfigured, onClose, hiddenProjects, onHiddenProjectsChange, allProjects }: ConfigureViewProps) {
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
  // Track selected key files + paste-mode contents so we can show a clear
  // "file loaded" indicator and disable Upload Pair until both are present.
  const [sliceKeyMode, setSliceKeyMode] = useState<'file' | 'paste'>('file');
  const [sliceKeyPrivName, setSliceKeyPrivName] = useState('');
  const [sliceKeyPubName, setSliceKeyPubName] = useState('');
  const [sliceKeyPrivText, setSliceKeyPrivText] = useState('');
  const [sliceKeyPubText, setSliceKeyPubText] = useState('');

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
    antigravity: false, codex: false, claude: false,
    aider: true, opencode: true, crush: true, deepagents: true,
  });

  // Tool install status & overlay
  const [installStatus, setInstallStatus] = useState<Record<string, ToolInstallInfo> | null>(null);
  const [installingToolId, setInstallingToolId] = useState<string | null>(null);
  const [uninstallingToolId, setUninstallingToolId] = useState<string | null>(null);

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
  const [customProviders, setCustomProviders] = useState<Array<{name: string; base_url: string; api_key: string; codex_provider?: boolean}>>([]);
  const [cpTestResults, setCpTestResults] = useState<Record<number, { testing: boolean; result?: SettingTestResult }>>({});

  // LLM key creation
  const [creatingLlmKey, setCreatingLlmKey] = useState(false);
  const [llmKeyMessage, setLlmKeyMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Views
  const [federatedViewEnabled, setFederatedViewEnabled] = useState(false);

  // Chameleon Cloud
  const [chameleonEnabled, setChameleonEnabled] = useState(false);
  const [chameleonSites, setChameleonSites] = useState<Record<string, ChameleonSiteSettings>>({});
  const [chameleonPasswordUsername, setChameleonPasswordUsername] = useState('');
  const [chameleonPassword, setChameleonPassword] = useState('');
  const [chameleonPasswordProjects, setChameleonPasswordProjects] = useState<api.ChameleonPasswordProjectOption[]>([]);
  const [selectedChameleonPasswordProject, setSelectedChameleonPasswordProject] = useState('');
  const [loadingChameleonProjects, setLoadingChameleonProjects] = useState(false);
  const [chameleonProjectLookupMessage, setChameleonProjectLookupMessage] = useState('');
  const [chameleonTestResults, setChameleonTestResults] = useState<Record<string, { ok: boolean; error: string; latency_ms: number }>>({});
  const [chameleonSshKey, setChameleonSshKey] = useState('');
  const [chameleonKeypairsBySite, setChameleonKeypairsBySite] = useState<Record<string, ChameleonKeypair[]>>({});
  const [loadingChameleonKeypairs, setLoadingChameleonKeypairs] = useState<Record<string, boolean>>({});
  const [uploadingChameleonKey, setUploadingChameleonKey] = useState<Record<string, boolean>>({});
  const [chameleonKeyUploadMessages, setChameleonKeyUploadMessages] = useState<Record<string, { type: 'success' | 'error'; text: string }>>({});

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
        setFederatedViewEnabled(s.views.federated_enabled ?? s.views.composite_enabled ?? false);
      }
      // Chameleon
      if (s.chameleon) {
        setChameleonEnabled(s.chameleon.enabled || false);
        setChameleonSites(s.chameleon.sites || {});
        const legacyPasswordSite = Object.values(s.chameleon.sites || {}).find((site: any) => site.username || site.password) as any;
        setChameleonPasswordUsername(s.chameleon.password_auth?.username || legacyPasswordSite?.username || '');
        setChameleonPassword(s.chameleon.password_auth?.password || legacyPasswordSite?.password || '');
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

  const loadInstallStatus = useCallback(async () => {
    try { setInstallStatus(await api.getToolInstallStatus()); } catch { /* ignore */ }
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
    loadInstallStatus();
  }, [loadStatus, loadKeySets, loadSettings, loadToolConfigs, loadUsers, loadModels, loadAgents, loadSkills, loadInstallStatus]);

  // Load projects when token is available.
  //
  // We try the Core-API endpoint (/api/projects via listUserProjects) first
  // because /api/config/projects reads from the JWT — and once the user has
  // saved a project, FABlib refreshes the token with a project-scoped JWT
  // whose `projects` claim only contains that one project. Falling back to
  // the JWT endpoint when Core API is unavailable (e.g. fablib not yet
  // configured on first login) gives us bastion_login + projects from the
  // freshly-uploaded token.
  const loadProjects = useCallback(async () => {
    try {
      api.invalidateUserProjectsCache();
      const data = await api.listUserProjects(true);
      setProjects(data.projects);
      if (data.projects.length > 0) {
        setSelectedProject((prev) => prev || data.projects[0].uuid);
      }
      return;
    } catch {
      // fall through to the JWT endpoint
    }
    try {
      const data = await api.getProjects();
      setProjects(data.projects);
      if (data.bastion_login) setBastionLogin(data.bastion_login);
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

  const handleConfigure = async () => {
    if (!selectedProject) {
      setMessage({ text: 'Select a project first', type: 'error' });
      return;
    }
    setLoading(true);
    try {
      const result = await api.autoSetup(selectedProject);
      setMessage({ text: `Configured: ${result.email || 'OK'}`, type: 'success' });
      const cfg = await api.getConfig();
      setStatus(cfg);
    } catch (err: any) {
      setMessage({ text: `Configure failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
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

  const resetSliceKeyForm = () => {
    setShowAddKeySet(false);
    setNewKeyName('');
    setSliceKeyPrivName('');
    setSliceKeyPubName('');
    setSliceKeyPrivText('');
    setSliceKeyPubText('');
    setSliceKeyMode('file');
    if (slicePrivKeyRef.current) slicePrivKeyRef.current.value = '';
    if (slicePubKeyRef.current) slicePubKeyRef.current.value = '';
  };

  const handleSliceKeyUpload = async (keyName: string) => {
    let privFile: File | undefined;
    let pubFile: File | undefined;

    if (sliceKeyMode === 'paste') {
      const priv = sliceKeyPrivText.trim();
      const pub = sliceKeyPubText.trim();
      if (!priv || !pub) {
        setMessage({ text: 'Paste both the private and public key text before uploading.', type: 'error' });
        return;
      }
      // Pasted private keys typically end with a newline; ensure that.
      privFile = new File([priv + '\n'], `${keyName}_priv`, { type: 'text/plain' });
      pubFile = new File([pub + '\n'], `${keyName}_pub.pub`, { type: 'text/plain' });
    } else {
      privFile = slicePrivKeyRef.current?.files?.[0];
      pubFile = slicePubKeyRef.current?.files?.[0];
      if (!privFile || !pubFile) {
        setMessage({ text: 'Choose both a private-key file and a public-key file before uploading.', type: 'error' });
        return;
      }
    }

    setLoading(true);
    try {
      await api.uploadSliceKeys(privFile, pubFile, keyName);
      setMessage({ text: `Slice keys uploaded to set '${keyName}'.`, type: 'success' });
      await loadStatus();
      await loadKeySets();
      resetSliceKeyForm();
    } catch (err: any) {
      setMessage({ text: `Slice key upload failed: ${err.message}`, type: 'error' });
    } finally {
      setLoading(false);
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
      const chameleonSitesForSave = Object.fromEntries(
        Object.entries(chameleonSites).map(([siteName, siteCfg]) => {
          const { username: _legacyUsername, password: _legacyPassword, ...siteWithoutPassword } = siteCfg as any;
          return [siteName, siteWithoutPassword];
        }),
      );
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
          password_auth: {
            username: chameleonPasswordUsername,
            password: chameleonPassword,
          },
          sites: chameleonSitesForSave,
        },
        services: {
          jupyter_port: jupyterPort,
          model_proxy_port: modelProxyPort,
        },
        tool_configs: settings?.tool_configs ?? {},
        views: {
          federated_enabled: federatedViewEnabled,
        },
      };

      // Save via unified settings API (writes settings.json + regenerates fabric_rc + ssh_config)
      await api.saveSettings(updatedSettings);

      // The API-key fields are write-only — clear local input state once
      // it's been sent to the server, otherwise hasUnsavedChanges keeps
      // flagging "Unsaved" after a successful save.
      setLitellmApiKey('');
      setNrpApiKey('');

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
        // Refresh settings too so the dirty-diff baseline matches what we
        // just wrote — otherwise the "Unsaved" badge stays orange after a
        // successful save.
        await Promise.all([loadStatus(), loadSettings(), loadProjects()]);
        onConfigured();
      } else {
        setMessage({ text: 'Configuration saved but some items are still missing.', type: 'error' });
        await Promise.all([loadStatus(), loadSettings(), loadProjects()]);
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
      // For the "project" test, validate the currently-selected row (which
      // may not yet be saved) instead of the saved active project. This makes
      // the Test Project button match the row the user actually clicked.
      const body = key === 'project' && selectedProject
        ? { project_id: selectedProject }
        : undefined;
      const result = await api.testSetting(key, body);
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

  // Dirty tracking — compares primary form fields against the loaded
  // settings baseline. Used to (a) disable Save when nothing changed and
  // (b) warn before closing the Settings overlay with pending edits.
  const hasUnsavedChanges = useMemo(() => {
    if (!settings) return false;
    if (selectedProject !== (settings.fabric.project_id || '')) return true;
    if (bastionLogin !== (settings.fabric.bastion_username || '')) return true;
    if (credmgrHost !== settings.fabric.hosts.credmgr) return true;
    if (orchestratorHost !== settings.fabric.hosts.orchestrator) return true;
    if (coreApiHost !== settings.fabric.hosts.core_api) return true;
    if (bastionHost !== settings.fabric.hosts.bastion) return true;
    if (amHost !== settings.fabric.hosts.artifact_manager) return true;
    if (logLevel !== settings.fabric.logging.level) return true;
    if (sshCommandLine !== settings.fabric.ssh_command_line) return true;
    if (aiServerUrl !== settings.ai.ai_server_url) return true;
    if (nrpServerUrl !== settings.ai.nrp_server_url) return true;
    if (federatedViewEnabled !== !!(settings.views?.federated_enabled ?? settings.views?.composite_enabled)) return true;
    if (chameleonEnabled !== !!settings.chameleon?.enabled) return true;
    if (chameleonSshKey !== (settings.chameleon?.ssh_key_file || '')) return true;
    if (chameleonPasswordUsername !== (settings.chameleon?.password_auth?.username || '')) return true;
    if (chameleonPassword !== (settings.chameleon?.password_auth?.password || '')) return true;
    if (serializeChameleonSitesForDirty(chameleonSites) !== serializeChameleonSitesForDirty(settings.chameleon?.sites)) return true;
    const baselineAvoid = new Set(settings.fabric.avoid_sites || []);
    if (baselineAvoid.size !== avoidSet.size) return true;
    for (const s of avoidSet) if (!baselineAvoid.has(s)) return true;
    if (litellmApiKey) return true;  // any new key input means pending change
    if (nrpApiKey) return true;
    return false;
  }, [
    settings, selectedProject, bastionLogin,
    credmgrHost, orchestratorHost, coreApiHost, bastionHost, amHost,
    logLevel, sshCommandLine, aiServerUrl, nrpServerUrl,
    federatedViewEnabled, chameleonEnabled, chameleonSshKey, chameleonPasswordUsername,
    chameleonPassword, chameleonSites, avoidSet,
    litellmApiKey, nrpApiKey,
  ]);

  const requestClose = useCallback(async () => {
    if (!onClose) return;
    if (hasUnsavedChanges) {
      const ok = await confirmDialog('You have unsaved settings changes. Discard them and close?', {
        title: 'Discard Settings Changes',
        confirmLabel: 'Discard',
        tone: 'danger',
      });
      if (!ok) return;
    }
    onClose();
  }, [hasUnsavedChanges, onClose]);

  // Warn on browser tab close / reload when there are pending edits.
  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasUnsavedChanges]);

  const effectiveKeyName = showAddKeySet && newKeyName.trim() ? newKeyName.trim() : 'default';

  const loadChameleonKeypairs = useCallback(async (siteName: string) => {
    if (!siteName) return;
    setLoadingChameleonKeypairs(prev => ({ ...prev, [siteName]: true }));
    try {
      const keypairs = await api.listChameleonKeypairs(siteName);
      setChameleonKeypairsBySite(prev => ({ ...prev, [siteName]: keypairs || [] }));
    } catch {
      setChameleonKeypairsBySite(prev => ({ ...prev, [siteName]: [] }));
    } finally {
      setLoadingChameleonKeypairs(prev => ({ ...prev, [siteName]: false }));
    }
  }, []);

  const handleChameleonKeypairPrivateKeyUpload = useCallback(async (siteName: string, keyName: string, file: File) => {
    const uploadKey = `${siteName}::${keyName}`;
    setUploadingChameleonKey(prev => ({ ...prev, [uploadKey]: true }));
    setChameleonKeyUploadMessages(prev => ({ ...prev, [uploadKey]: { type: 'success', text: 'Uploading...' } }));
    try {
      await api.uploadChameleonKeypairPrivateKey(siteName, keyName, file);
      setChameleonKeyUploadMessages(prev => ({ ...prev, [uploadKey]: { type: 'success', text: 'Private key saved' } }));
      await loadChameleonKeypairs(siteName);
    } catch (e: any) {
      setChameleonKeyUploadMessages(prev => ({ ...prev, [uploadKey]: { type: 'error', text: e?.message || 'Upload failed' } }));
    } finally {
      setUploadingChameleonKey(prev => ({ ...prev, [uploadKey]: false }));
    }
  }, [loadChameleonKeypairs]);

  useEffect(() => {
    if (!chameleonEnabled || activeSection !== 'chameleon') return;
    for (const siteName of Object.keys(chameleonSites)) {
      if (chameleonKeypairsBySite[siteName] === undefined && !loadingChameleonKeypairs[siteName]) {
        void loadChameleonKeypairs(siteName);
      }
    }
  }, [
    activeSection,
    chameleonEnabled,
    chameleonSites,
    chameleonKeypairsBySite,
    loadingChameleonKeypairs,
    loadChameleonKeypairs,
  ]);

  const applyChameleonPasswordProject = (projectName: string) => {
    setSelectedChameleonPasswordProject(projectName);
    const project = chameleonPasswordProjects.find(p => p.name === projectName);
    if (!project) return;
    setChameleonSites(prev => {
      const next = { ...prev };
      for (const [siteName, projectId] of Object.entries(project.sites)) {
        if (next[siteName]) {
          next[siteName] = { ...next[siteName], project_id: projectId };
        }
      }
      return next;
    });
    setChameleonProjectLookupMessage(`Set project ID for ${project.site_count} site${project.site_count === 1 ? '' : 's'}.`);
  };

  const loadChameleonPasswordProjects = async () => {
    if (!chameleonPasswordUsername.trim() || !chameleonPassword) {
      setChameleonProjectLookupMessage('Enter the Chameleon username and password first.');
      return;
    }
    setLoadingChameleonProjects(true);
    setChameleonProjectLookupMessage('');
    try {
      const result = await api.listChameleonPasswordAuthProjects({
        username: chameleonPasswordUsername.trim(),
        password: chameleonPassword,
        sites: Object.keys(chameleonSites),
      });
      setChameleonPasswordProjects(result.projects);
      setSelectedChameleonPasswordProject('');
      const failed = Object.entries(result.sites).filter(([, value]) => !value.ok);
      if (result.projects.length === 0) {
        setChameleonProjectLookupMessage(failed.length ? `No projects found. ${failed.length} site lookup failed.` : 'No projects found.');
      } else if (failed.length) {
        setChameleonProjectLookupMessage(`Loaded ${result.projects.length} project names. ${failed.length} site lookup failed.`);
      } else {
        setChameleonProjectLookupMessage(`Loaded ${result.projects.length} project names.`);
      }
    } catch (e: any) {
      setChameleonProjectLookupMessage(`Project lookup failed: ${e.message}`);
    } finally {
      setLoadingChameleonProjects(false);
    }
  };

  /* ---------- User add/switch/delete ---------- */

  const handleAddUser = async () => {
    try {
      const { login_url } = await api.getLoginUrl();
      window.open(login_url, 'fabric-login', 'width=600,height=700');
      setMessage({ text: 'Complete login in the popup to add the user…', type: 'success' });
    } catch (err: any) {
      setMessage({ text: `Could not start login: ${err.message}`, type: 'error' });
    }
  };

  /* ---------- Section renderers ---------- */

  const renderProfile = () => {
    const activeUser = registeredUsers.find((u) => u.is_active);
    // Multi-user is standalone-only; in K8s (sub-path deployment) each user has
    // their own pod, so hide the in-container user switcher.
    const multiUser = !(typeof window !== 'undefined' && window.__LOOMAI_BASE_PATH);
    return (
    <>
      {/* User selector — choose the active FABRIC identity, add another, or delete one */}
      {multiUser && (
      <div className="configure-section">
        <h3>User</h3>
        <p>
          Select the active FABRIC identity, add another, or delete one. Each user's
          tokens, keys, slices, artifacts, and settings are stored separately.
        </p>
        <div className="user-selector-row" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <InAppSelect
            className="user-selector"
            value={activeUser?.uuid || '__add__'}
            disabled={switchingUser}
            onChange={async (e) => {
              const val = e.target.value;
              if (val === '__add__') { handleAddUser(); return; }
              if (val === activeUser?.uuid) return;
              setSwitchingUser(true);
              try {
                await api.switchUser(val);
                const u = registeredUsers.find((x) => x.uuid === val);
                setMessage({ text: `Switched to ${u?.name || u?.email || val}`, type: 'success' });
                await Promise.all([loadStatus(), loadUsers(), loadSettings(), loadKeySets()]);
                await loadProjects();
              } catch (err: any) {
                setMessage({ text: `Switch failed: ${err.message}`, type: 'error' });
              } finally {
                setSwitchingUser(false);
              }
            }}
          >
            {registeredUsers.map((u) => (
              <option key={u.uuid} value={u.uuid}>
                {u.name || u.email || `${u.uuid.slice(0, 8)}…`}
                {u.name && u.email ? ` (${u.email})` : ''}
              </option>
            ))}
            <option value="__add__">➕ Add a user…</option>
          </InAppSelect>
          {switchingUser && <span className="muted">Switching…</span>}
          {activeUser && (
            <button
              className="btn btn-sm btn-danger"
              disabled={switchingUser}
              onClick={async () => {
                if (!await confirmDialog(
                  `Delete ${activeUser.name || activeUser.email || activeUser.uuid}? This permanently `
                  + `removes their folder — tokens, keys, slices, artifacts, and settings.`,
                  {
                    title: 'Delete User',
                    confirmLabel: 'Delete',
                    tone: 'danger',
                  },
                )) return;
                try {
                  await api.removeUser(activeUser.uuid, true);
                  setMessage({ text: 'User deleted', type: 'success' });
                  await Promise.all([loadUsers(), loadStatus(), loadSettings(), loadKeySets()]);
                  await loadProjects();
                } catch (err: any) {
                  setMessage({ text: `Delete failed: ${err.message}`, type: 'error' });
                }
              }}
            >
              Delete user
            </button>
          )}
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
        <p>Upload a token file, or configure FABRIC credentials from the current token.</p>
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
            onClick={handleConfigure}
            disabled={loading || !status?.has_token}
            title={!status?.has_token ? 'Upload a token first' : 'Generate SSH keys, bastion config, and project setup'}
          >
            Configure
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
          data-testid="configure-bastion-login"
          value={bastionLogin}
          onChange={(e) => setBastionLogin(e.target.value)}
          placeholder="e.g. user_name_0001234567"
          title="Your FABRIC bastion login (auto-detected from token)"
        />
      </div>
    </>
    );
  };

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
              if (status?.has_bastion_key && !await confirmDialog('Regenerate bastion key? This will replace the existing key.', {
                title: 'Regenerate Bastion Key',
                confirmLabel: 'Regenerate',
                tone: 'danger',
              })) return;
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
        ) : (() => {
          const filesReady = !!sliceKeyPrivName && !!sliceKeyPubName;
          const pasteReady = !!sliceKeyPrivText.trim() && !!sliceKeyPubText.trim();
          const uploadReady = sliceKeyMode === 'file' ? filesReady : pasteReady;
          return (
          <div className="add-key-set-form">
            <div className="btn-row">
              <input
                type="text"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value.replace(/[^a-zA-Z0-9_-]/g, ''))}
                placeholder="Key set name (e.g. project-x)"
                style={{ flex: 1, marginBottom: 0 }}
              />
              <button className="btn" onClick={resetSliceKeyForm}>Cancel</button>
            </div>

            <p style={{ fontSize: 11, color: 'var(--fabric-text-muted)', margin: '8px 0 4px' }}>
              Provide both the private and public halves of an SSH key pair. You can either upload the files or paste their contents directly.
            </p>

            <div className="btn-row" style={{ marginTop: 0, gap: 4 }}>
              <button
                type="button"
                className={`btn-sm${sliceKeyMode === 'file' ? ' primary' : ''}`}
                onClick={() => setSliceKeyMode('file')}
                disabled={loading}
              >Upload files</button>
              <button
                type="button"
                className={`btn-sm${sliceKeyMode === 'paste' ? ' primary' : ''}`}
                onClick={() => setSliceKeyMode('paste')}
                disabled={loading}
              >Paste text</button>
            </div>

            <input
              ref={slicePrivKeyRef}
              type="file"
              className="file-input-hidden"
              onChange={(e) => setSliceKeyPrivName(e.target.files?.[0]?.name || '')}
            />
            <input
              ref={slicePubKeyRef}
              type="file"
              className="file-input-hidden"
              onChange={(e) => setSliceKeyPubName(e.target.files?.[0]?.name || '')}
            />

            {sliceKeyMode === 'file' ? (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div className="btn-row" style={{ alignItems: 'center', gap: 8 }}>
                  <button
                    className="btn"
                    onClick={() => slicePrivKeyRef.current?.click()}
                    disabled={loading}
                  >Private Key…</button>
                  <span style={{ fontSize: 12 }}>
                    {sliceKeyPrivName
                      ? <span style={{ color: '#008e7a' }}>{'✓'} {sliceKeyPrivName}</span>
                      : <span style={{ color: 'var(--fabric-text-muted)' }}>No file chosen</span>}
                  </span>
                </div>
                <div className="btn-row" style={{ alignItems: 'center', gap: 8 }}>
                  <button
                    className="btn"
                    onClick={() => slicePubKeyRef.current?.click()}
                    disabled={loading}
                  >Public Key…</button>
                  <span style={{ fontSize: 12 }}>
                    {sliceKeyPubName
                      ? <span style={{ color: '#008e7a' }}>{'✓'} {sliceKeyPubName}</span>
                      : <span style={{ color: 'var(--fabric-text-muted)' }}>No file chosen</span>}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div>
                  <label style={{ fontSize: 11, display: 'block', marginBottom: 2 }}>Private key (PEM / OPENSSH)</label>
                  <textarea
                    value={sliceKeyPrivText}
                    onChange={(e) => setSliceKeyPrivText(e.target.value)}
                    placeholder={'-----BEGIN OPENSSH PRIVATE KEY-----\n…\n-----END OPENSSH PRIVATE KEY-----'}
                    rows={5}
                    style={{ width: '100%', fontFamily: 'monospace', fontSize: 11 }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: 11, display: 'block', marginBottom: 2 }}>Public key</label>
                  <textarea
                    value={sliceKeyPubText}
                    onChange={(e) => setSliceKeyPubText(e.target.value)}
                    placeholder="ssh-ed25519 AAAA... comment"
                    rows={2}
                    style={{ width: '100%', fontFamily: 'monospace', fontSize: 11 }}
                  />
                </div>
              </div>
            )}

            <div className="btn-row" style={{ marginTop: 10, alignItems: 'center', gap: 8 }}>
              <button
                className="btn primary"
                onClick={() => handleSliceKeyUpload(effectiveKeyName)}
                disabled={loading || !uploadReady}
                title={uploadReady ? `Upload to key set '${effectiveKeyName}'` : 'Provide both a private and public key first'}
              >
                {loading ? 'Uploading…' : 'Upload Pair'}
              </button>
              <span style={{ flex: 1, fontSize: 11, color: 'var(--fabric-text-muted)' }}>
                {!uploadReady
                  ? (sliceKeyMode === 'file' ? 'Choose both a private and public key file to enable upload.' : 'Paste both keys to enable upload.')
                  : `Ready to upload to '${effectiveKeyName}'.`}
              </span>
              <button className="btn success" onClick={() => handleGenerateKeys(effectiveKeyName)} disabled={loading}>
                Generate
              </button>
            </div>
          </div>
          );
        })()}

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
        <InAppSelect value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
          <option>DEBUG</option>
          <option>INFO</option>
          <option>WARNING</option>
          <option>ERROR</option>
        </InAppSelect>
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
        <p>Click a project to select it, then press <strong>Save</strong> to make it active. The eye toggle hides a project from the switcher.</p>
        {allRegular.length === 0 && status?.has_token && (
          <p style={{ color: 'var(--fabric-text-muted)', fontStyle: 'italic' }}>Loading projects...</p>
        )}
        {allRegular.length === 0 && !status?.has_token && (
          <p style={{ color: 'var(--fabric-text-muted)', fontStyle: 'italic' }}>Login to load your projects.</p>
        )}
        <div className="project-toggle-list">
          {allRegular.map((p) => {
            const isHidden = hiddenProjects?.has(p.uuid) ?? false;
            // "Active" means the project the backend is currently configured
            // for (saved). "Selected" means the row the user clicked but
            // hasn't saved yet. Pending = selected != active.
            const isActive = p.uuid === status?.project_id;
            const isSelected = p.uuid === selectedProject;
            const isPending = isSelected && !isActive;
            return (
              <div
                key={p.uuid}
                className={`project-toggle-row${isActive ? ' project-active-row' : ''}${isPending ? ' project-pending-row' : ''}${isHidden ? ' hidden-project' : ''}`}
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
                {isPending && <span className="project-toggle-pending">selected — save to apply</span>}
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
                // Reload settings so the new key is in the settings state
                // (prevents handleSave from overwriting it with stale empty value)
                await loadSettings();
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
          <div key={i} style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="text" placeholder="Name" value={cp.name} style={{ width: 80, fontSize: 12 }}
              onChange={e => { const next = [...customProviders]; next[i] = { ...cp, name: e.target.value }; setCustomProviders(next); }} />
            <input type="text" placeholder="Base URL" value={cp.base_url} style={{ flex: 1, fontSize: 12, minWidth: 180 }}
              onChange={e => { const next = [...customProviders]; next[i] = { ...cp, base_url: e.target.value }; setCustomProviders(next); }} />
            <input type="password" placeholder="API Key" value={cp.api_key} style={{ width: 120, fontSize: 12 }}
              onChange={e => { const next = [...customProviders]; next[i] = { ...cp, api_key: e.target.value }; setCustomProviders(next); }} />
            <button className="test-btn" disabled={!cp.base_url || cpTestResults[i]?.testing}
              style={{ fontSize: 11, padding: '2px 8px' }}
              onClick={async () => {
                setCpTestResults(prev => ({ ...prev, [i]: { testing: true } }));
                try {
                  const result = await api.testCustomProvider(cp.base_url, cp.api_key);
                  setCpTestResults(prev => ({ ...prev, [i]: { testing: false, result } }));
                } catch {
                  setCpTestResults(prev => ({ ...prev, [i]: { testing: false, result: { ok: false, message: 'Request failed' } } }));
                }
              }}>
              {cpTestResults[i]?.testing ? <span className="test-spinner" /> : 'Test'}
            </button>
            <button
              className={`test-btn${cp.codex_provider ? ' codex-active' : ''}`}
              style={{ fontSize: 10, padding: '2px 6px' }}
              title={cp.codex_provider ? 'This provider is used by Codex CLI. Click to remove.' : 'Use this provider for Codex CLI'}
              onClick={() => {
                const next = customProviders.map((p, j) => ({
                  ...p,
                  codex_provider: j === i ? !p.codex_provider : false,
                }));
                setCustomProviders(next);
              }}
            >
              Codex{cp.codex_provider ? ' \u2713' : ''}
            </button>
            <button style={{ fontSize: 11, padding: '2px 6px', cursor: 'pointer', border: '1px solid var(--fabric-border)', borderRadius: 3, background: 'var(--fabric-bg-tint)', color: 'var(--fabric-text-muted)' }}
              onClick={() => { setCustomProviders(customProviders.filter((_, j) => j !== i)); setCpTestResults(prev => { const n = { ...prev }; delete n[i]; return n; }); }}>X</button>
            {cpTestResults[i]?.result && (
              <span className={`test-result ${cpTestResults[i].result!.ok ? 'test-ok' : 'test-fail'}`} style={{ fontSize: 11 }}>
                {cpTestResults[i].result!.ok ? '\u2713' : '\u2717'} {cpTestResults[i].result!.message}
                {cpTestResults[i].result!.latency_ms != null && <span className="test-latency"> ({cpTestResults[i].result!.latency_ms}ms)</span>}
              </span>
            )}
          </div>
        ))}
        <button className="btn" style={{ marginTop: 6, fontSize: 12, padding: '4px 12px' }}
          onClick={() => setCustomProviders([...customProviders, { name: '', base_url: '', api_key: '', codex_provider: false }])}>
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

  const handleUninstall = async (toolId: string) => {
    if (!await confirmDialog(`Uninstall ${installStatus?.[toolId]?.display_name || toolId}? This will remove the tool and free disk space.`, {
      title: 'Uninstall AI Tool',
      confirmLabel: 'Uninstall',
      tone: 'danger',
    })) return;
    setUninstallingToolId(toolId);
    try {
      const result = await api.uninstallTool(toolId);
      if (result.status === 'uninstalled' || result.status === 'not_installed') {
        setAiTools((prev) => ({ ...prev, [toolId]: false }));
        setMessage({ text: `${installStatus?.[toolId]?.display_name || toolId} uninstalled`, type: 'success' });
      } else {
        setMessage({ text: `Failed to uninstall ${toolId}`, type: 'error' });
      }
      await loadInstallStatus();
    } catch (err: any) {
      setMessage({ text: `Uninstall failed: ${err.message}`, type: 'error' });
    } finally {
      setUninstallingToolId(null);
    }
  };

  const renderAITools = () => (
    <>
      {installingToolId && (
        <ToolInstallOverlay
          toolId={installingToolId}
          onComplete={() => {
            const justInstalled = installingToolId;
            setInstallingToolId(null);
            loadInstallStatus();
            setAiTools((prev) => ({ ...prev, [justInstalled]: true }));
          }}
          onError={(msg) => {
            setInstallingToolId(null);
            setMessage({ text: msg, type: 'error' });
          }}
        />
      )}
      <div className="configure-section">
        <h3 data-help-id="settings.ai-tools">Enabled Tools</h3>
        <p>Choose which AI tools appear in the AI Companion launcher.</p>
        <div className="ai-tool-toggles">
          {([
            { id: 'antigravity', label: 'Antigravity', desc: 'Google agentic coding CLI (free with Google account)' },
            { id: 'codex', label: 'Codex', desc: 'OpenAI coding agent CLI (free with OpenAI account)' },
            { id: 'claude', label: 'Claude Code', desc: 'Anthropic CLI (requires your own account)' },
            { id: 'aider', label: 'Aider', desc: 'AI pair programming terminal' },
            { id: 'opencode', label: 'OpenCode', desc: 'Terminal-based AI coding assistant' },
            { id: 'crush', label: 'Crush', desc: 'Terminal AI assistant (Charm)' },
            { id: 'deepagents', label: 'Deep Agents', desc: 'LangChain coding agent with planning and memory' },
          ] as const).map((tool) => {
            const info = installStatus?.[tool.id];
            // Only show as installed if we have status data confirming it
            const statusLoaded = installStatus !== null;
            const isInstalled = statusLoaded ? (!info || info.installed) : true;
            const sizeEst = info?.size_estimate || '';
            const isUninstalling = uninstallingToolId === tool.id;

            return (
              <label key={tool.id} className={`ai-tool-toggle-row${statusLoaded && !isInstalled ? ' not-installed' : ''}`}>
                <input
                  type="checkbox"
                  checked={aiTools[tool.id] ?? false}
                  disabled={statusLoaded && !isInstalled}
                  onChange={(e) => setAiTools((prev) => ({ ...prev, [tool.id]: e.target.checked }))}
                />
                <span className="ai-tool-toggle-info">
                  <span className="ai-tool-toggle-name">{tool.label}</span>
                  <span className="ai-tool-toggle-desc">{tool.desc}</span>
                </span>
                {!statusLoaded ? null : isInstalled ? (
                  <span className="ai-tool-status-actions">
                    <span className="ai-tool-installed-badge">{'\u2713'}</span>
                    <button
                      className="ai-tool-uninstall-btn"
                      disabled={isUninstalling}
                      onClick={(e) => { e.preventDefault(); handleUninstall(tool.id); }}
                      title="Uninstall this tool"
                    >
                      {isUninstalling ? 'Removing...' : 'Uninstall'}
                    </button>
                  </span>
                ) : (
                  <button
                    className="ai-tool-install-btn"
                    onClick={(e) => { e.preventDefault(); setInstallingToolId(tool.id); }}
                  >
                    Install{sizeEst ? ` (${sizeEst})` : ''}
                  </button>
                )}
              </label>
            );
          })}
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
            checked={federatedViewEnabled}
            onChange={e => setFederatedViewEnabled(e.target.checked)}
            style={{ marginRight: 4 }}
          />
          Enable Federated Slices View
        </label>
        <span style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>(cross-testbed experiments)</span>
      </div>
      {chameleonEnabled && (
        <div style={{ marginTop: 8 }}>
          <p>
            Enter one shared Chameleon username and password, then choose per site whether to use password auth or that site's application credential. Both credential sets are saved, so switching modes does not clear the other mode's values.
          </p>
          <div style={{ marginTop: 8, padding: 8, border: '1px solid var(--fabric-border)', borderRadius: 6 }}>
            <p style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>Shared Password Auth</p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
              <input
                type="email"
                placeholder="Chameleon username or email"
                value={chameleonPasswordUsername}
                onChange={e => setChameleonPasswordUsername(e.target.value)}
                style={{ fontSize: 11 }}
              />
              <input
                type="password"
                placeholder="Chameleon password"
                value={chameleonPassword}
                onChange={e => setChameleonPassword(e.target.value)}
                style={{ fontSize: 11 }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="test-btn"
                onClick={loadChameleonPasswordProjects}
                disabled={loadingChameleonProjects || !chameleonPasswordUsername.trim() || !chameleonPassword}
              >
                {loadingChameleonProjects ? 'Loading Projects...' : 'Load Projects'}
              </button>
              <InAppSelect
                value={selectedChameleonPasswordProject}
                onChange={e => applyChameleonPasswordProject(e.target.value)}
                disabled={chameleonPasswordProjects.length === 0}
                style={{ fontSize: 11, minWidth: 220 }}
              >
                <option value="">Select project by name</option>
                {chameleonPasswordProjects.map(project => (
                  <option key={project.name} value={project.name}>
                    {project.name} ({project.site_count} site{project.site_count === 1 ? '' : 's'})
                  </option>
                ))}
              </InAppSelect>
              {chameleonProjectLookupMessage && (
                <span style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>{chameleonProjectLookupMessage}</span>
              )}
            </div>
          </div>
          {Object.entries(chameleonSites).map(([siteName, siteCfg]) => {
            const authType: ChameleonAuthType = siteCfg.auth_type || 'application_credential';
            const siteDefaultKey = siteCfg.default_key_name || '';
            const siteKeypairs = chameleonKeypairsBySite[siteName] || [];
            const siteKeyNames = Array.from(new Set(
              siteKeypairs
                .map(keypair => keypair.name || '')
                .filter(Boolean),
            ));
            if (siteDefaultKey && !siteKeyNames.includes(siteDefaultKey)) {
              siteKeyNames.push(siteDefaultKey);
            }
            const updateSite = (updates: Partial<ChameleonSiteSettings>) => {
              setChameleonSites(prev => ({ ...prev, [siteName]: { ...prev[siteName], ...updates } }));
            };
            return (
              <div key={siteName} style={{ marginTop: 8, padding: 8, border: '1px solid var(--fabric-border)', borderRadius: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                  <p style={{ fontWeight: 600, fontSize: 12, margin: 0 }}>{siteName}</p>
                  <div style={{ display: 'inline-flex', border: '1px solid var(--fabric-border)', borderRadius: 6, overflow: 'hidden' }}>
                    {([
                      ['application_credential', 'Application credential'],
                      ['password', 'Password auth'],
                    ] as Array<[ChameleonAuthType, string]>).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => updateSite({ auth_type: value })}
                        style={{
                          border: 0,
                          borderRight: value === 'application_credential' ? '1px solid var(--fabric-border)' : 0,
                          padding: '4px 8px',
                          fontSize: 11,
                          cursor: 'pointer',
                          background: authType === value ? 'var(--fabric-primary)' : 'transparent',
                          color: authType === value ? '#fff' : 'var(--fabric-text)',
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                {authType === 'application_credential' ? (
                  <>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                      <input type="text" placeholder="App Credential ID" value={siteCfg.app_credential_id || ''}
                        onChange={e => updateSite({ app_credential_id: e.target.value })}
                        style={{ fontSize: 11 }} />
                      <input type="password" placeholder="App Credential Secret" value={siteCfg.app_credential_secret || ''}
                        onChange={e => updateSite({ app_credential_secret: e.target.value })}
                        style={{ fontSize: 11 }} />
                    </div>
                    <input type="text" placeholder="Project ID for this site" value={siteCfg.project_id || ''}
                      onChange={e => updateSite({ project_id: e.target.value })}
                      style={{ fontSize: 11, marginTop: 4, width: '100%' }} />
                  </>
                ) : (
                  <>
                    <input type="text" placeholder="Project ID" value={siteCfg.project_id || ''}
                      onChange={e => updateSite({ project_id: e.target.value })}
                      style={{ fontSize: 11, marginTop: 4, width: '100%' }} />
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginTop: 4 }}>
                      <input type="text" placeholder="OIDC Client ID" value={siteCfg.client_id || ''}
                        onChange={e => updateSite({ client_id: e.target.value })}
                        style={{ fontSize: 11 }} />
                      <input type="text" placeholder="Client Secret" value={siteCfg.client_secret ?? 'none'}
                        onChange={e => updateSite({ client_secret: e.target.value })}
                        style={{ fontSize: 11 }} />
                    </div>
                  </>
                )}
                <div style={{ marginTop: 6 }}>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 3 }}>
                    Default SSH key
                  </label>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 4, alignItems: 'center' }}>
                    <InAppSelect
                      value={siteDefaultKey}
                      onChange={e => updateSite({ default_key_name: e.target.value })}
                      style={{ fontSize: 11, width: '100%' }}
                      data-testid={`chameleon-default-key-${siteName}`}
                    >
                      <option value="">Use LoomAI managed key (loomai-key)</option>
                      {siteKeyNames.map(keyName => (
                        <option key={keyName} value={keyName}>
                          {keyName}
                        </option>
                      ))}
                    </InAppSelect>
                    <button
                      type="button"
                      className="test-btn"
                      onClick={() => loadChameleonKeypairs(siteName)}
                      disabled={!!loadingChameleonKeypairs[siteName]}
                    >
                      {loadingChameleonKeypairs[siteName] ? 'Loading...' : 'Refresh Keys'}
                    </button>
                  </div>
                </div>
                <div style={{ marginTop: 8 }}>
                  <label style={{ display: 'block', fontSize: 11, fontWeight: 600, marginBottom: 3 }}>
                    Keypair private keys
                  </label>
                  <div style={{ display: 'grid', gap: 4 }}>
                    {siteKeypairs.length === 0 ? (
                      <div style={{ fontSize: 11, color: 'var(--fabric-text-muted)' }}>No registered keypairs loaded.</div>
                    ) : siteKeypairs.map(keypair => {
                      const keyName = keypair.name || '';
                      if (!keyName) return null;
                      const uploadKey = `${siteName}::${keyName}`;
                      const uploadMessage = chameleonKeyUploadMessages[uploadKey];
                      return (
                        <div
                          key={keyName}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'minmax(140px, 1fr) minmax(110px, auto) minmax(190px, auto)',
                            alignItems: 'center',
                            gap: 6,
                            padding: '4px 0',
                            borderTop: '1px solid var(--fabric-border)',
                          }}
                        >
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: 11, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {keyName}
                            </div>
                            {keypair.fingerprint && (
                              <div style={{ fontSize: 10, color: 'var(--fabric-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {keypair.fingerprint}
                              </div>
                            )}
                          </div>
                          <span
                            title={keypair.private_key_path || ''}
                            style={{
                              fontSize: 10,
                              color: keypair.has_private_key ? 'var(--fabric-success, #39B54A)' : 'var(--fabric-text-muted)',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {keypair.has_private_key ? 'private key saved' : 'private key missing'}
                          </span>
                          <div style={{ display: 'grid', gap: 2 }}>
                            <input
                              type="file"
                              accept=".pem,.key,.txt"
                              aria-label={`Upload private key for ${keyName}`}
                              data-testid={`chameleon-keypair-private-key-${siteName}-${keyName}`}
                              disabled={!!uploadingChameleonKey[uploadKey]}
                              onChange={e => {
                                const file = e.target.files?.[0];
                                if (file) void handleChameleonKeypairPrivateKeyUpload(siteName, keyName, file);
                                e.currentTarget.value = '';
                              }}
                              style={{ fontSize: 10, maxWidth: '100%' }}
                            />
                            {uploadMessage && (
                              <span
                                style={{
                                  fontSize: 10,
                                  color: uploadMessage.type === 'success' ? 'var(--fabric-success, #39B54A)' : 'var(--fabric-danger, #b91c1c)',
                                }}
                              >
                                {uploadingChameleonKey[uploadKey] ? 'Uploading...' : uploadMessage.text}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
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
            );
          })}
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
                      if (!await confirmDialog(`Delete ${type} "${item.name}"?`, {
                        title: `Delete ${type}`,
                        confirmLabel: 'Delete',
                        tone: 'danger',
                      })) return;
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
    <div className="configure-view" data-testid="configure-view">
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
          {hasUnsavedChanges && (
            <span className="configure-dirty-badge" title="You have unsaved changes">
              {'●'} Unsaved
            </span>
          )}
          <button
            className="btn primary"
            onClick={handleSave}
            disabled={saving || !status?.has_token || !selectedProject || !bastionLogin || !hasUnsavedChanges}
            title={!hasUnsavedChanges ? 'No changes to save' : 'Save settings'}
            data-testid="configure-save"
          >
            {saving ? 'Saving...' : hasUnsavedChanges ? 'Save' : 'Saved'}
          </button>
          {onClose && (
            <button className="btn configure-close-btn" onClick={requestClose}>
              Close
            </button>
          )}
        </div>
      </div>

      {/* Mobile dropdown (< 768px) */}
      <div className="configure-mobile-nav">
        <InAppSelect
          value={activeSection}
          onChange={(e) => setActiveSection(e.target.value as SectionId)}
        >
          {SECTIONS.map((s) => (
            <option key={s.id} value={s.id}>{s.icon} {s.label}</option>
          ))}
        </InAppSelect>
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
                data-testid="configure-section-tab"
                data-section={s.id}
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
              data-testid="configure-test-all"
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
