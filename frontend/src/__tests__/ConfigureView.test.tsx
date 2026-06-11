import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ConfigureView from '../components/ConfigureView';
import * as api from '../api/client';

vi.mock('../components/ToolInstallOverlay', () => ({
  default: () => <div data-testid="tool-install-overlay" />,
}));

vi.mock('../api/client', () => ({
  getConfig: vi.fn(),
  listSliceKeySets: vi.fn(),
  getSettings: vi.fn(),
  getToolConfigs: vi.fn(),
  listUsers: vi.fn(),
  getAiModels: vi.fn(),
  getAgents: vi.fn(),
  getSkills: vi.fn(),
  getToolInstallStatus: vi.fn(),
  getProjects: vi.fn(),
  listSites: vi.fn(),
  listChameleonKeypairs: vi.fn(),
  uploadChameleonKeypairPrivateKey: vi.fn(),
  saveSettings: vi.fn(),
  saveConfig: vi.fn(),
  testAllSettings: vi.fn(),
  testSetting: vi.fn(),
  resetToolConfig: vi.fn(),
}));

function mockSettings() {
  return {
    schema_version: 1,
    paths: {
      storage_dir: '/home/fabric/work',
      config_dir: '/home/fabric/work/fabric_config',
      artifacts_dir: '/home/fabric/work/my_artifacts',
      slices_dir: '/home/fabric/work/my_slices',
      notebooks_dir: '/home/fabric/work/notebooks',
      ai_tools_dir: '/home/fabric/work/.ai-tools',
      token_file: '/home/fabric/work/fabric_config/id_token.json',
      bastion_key_file: '/home/fabric/work/fabric_config/fabric_bastion_key',
      slice_keys_dir: '/home/fabric/work/fabric_config/slice_keys',
      ssh_config_file: '/home/fabric/work/fabric_config/ssh_config',
      log_file: '/tmp/fablib/fablib.log',
    },
    fabric: {
      project_id: 'project-1',
      bastion_username: 'user_0000000000',
      hosts: {
        credmgr: 'cm.fabric-testbed.net',
        orchestrator: 'orchestrator.fabric-testbed.net',
        core_api: 'uis.fabric-testbed.net',
        bastion: 'bastion.fabric-testbed.net',
        artifact_manager: 'artifacts.fabric-testbed.net',
      },
      logging: { level: 'INFO' },
      avoid_sites: [],
      ssh_command_line: 'ssh {{ _self_.username }}@{{ _self_.management_ip }}',
    },
    ai: {
      fabric_api_key: 'mock-key',
      nrp_api_key: '',
      ai_server_url: 'https://ai.fabric-testbed.net',
      nrp_server_url: 'https://ellm.nrp-nautilus.io',
      custom_providers: [],
      tools: { aider: true, opencode: true, crush: true, deepagents: true },
    },
    chameleon: { enabled: true, sites: {}, ssh_key_file: '' },
    services: { jupyter_port: 8889, model_proxy_port: 9199 },
    tool_configs: {},
    views: { composite_enabled: true },
  };
}

function renderConfigure() {
  return render(<ConfigureView onConfigured={() => {}} allProjects={[{ uuid: 'project-1', name: 'TestProject' } as any]} />);
}

describe('ConfigureView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getConfig).mockResolvedValue({
      configured: true,
      has_token: true,
      has_bastion_key: true,
      has_slice_key: true,
      project_id: 'project-1',
      bastion_username: 'user_0000000000',
    } as any);
    vi.mocked(api.listSliceKeySets).mockResolvedValue([]);
    vi.mocked(api.getSettings).mockResolvedValue(mockSettings() as any);
    vi.mocked(api.getToolConfigs).mockResolvedValue([]);
    vi.mocked(api.listUsers).mockResolvedValue({ users: [], active_user: null } as any);
    vi.mocked(api.getAiModels).mockResolvedValue({
      default: 'fabric/mock-model',
      fabric: [{ id: 'fabric/mock-model', healthy: true }],
      nrp: [],
      custom: {},
      has_key: { fabric: true, nrp: false },
      models: ['fabric/mock-model'],
      nrp_models: [],
    } as any);
    vi.mocked(api.getAgents).mockResolvedValue([]);
    vi.mocked(api.getSkills).mockResolvedValue([]);
    vi.mocked(api.getToolInstallStatus).mockResolvedValue({});
    vi.mocked(api.getProjects).mockResolvedValue({
      projects: [{ uuid: 'project-1', name: 'TestProject' }],
      bastion_login: 'user_0000000000',
      email: 'test@example.com',
      name: 'Test User',
    } as any);
    vi.mocked(api.listSites).mockResolvedValue([{ name: 'RENC' }, { name: 'TACC' }] as any);
    vi.mocked(api.listChameleonKeypairs).mockResolvedValue([]);
    vi.mocked(api.uploadChameleonKeypairPrivateKey).mockResolvedValue({
      status: 'saved',
      site: 'CHI@TACC',
      name: 'site-key',
      key_path: '/home/fabric/work/fabric_config/chameleon_key_CHI@TACC_site-key',
      has_private_key: true,
    } as any);
    vi.mocked(api.saveSettings).mockImplementation(async settings => settings as any);
    vi.mocked(api.saveConfig).mockResolvedValue({ status: 'saved', configured: true });
    vi.mocked(api.testAllSettings).mockResolvedValue({
      token: { ok: true, message: 'Token ok' },
      fablib: { ok: true, message: 'FABlib ok' },
    });
  });

  it('renders settings sections and runs the all-settings check', async () => {
    renderConfigure();

    expect(await screen.findByTestId('configure-view')).toBeInTheDocument();
    expect(screen.getAllByTestId('configure-section-tab').length).toBeGreaterThan(3);

    fireEvent.click(screen.getByTestId('configure-test-all'));

    await waitFor(() => expect(api.testAllSettings).toHaveBeenCalled());
    expect(await screen.findByText('token')).toBeInTheDocument();
    expect(screen.getByText(/FABlib ok/)).toBeInTheDocument();
  });

  it('saves unified settings and the legacy FABlib config', async () => {
    renderConfigure();

    // Save is disabled until the form is dirty (dirty-tracking) — edit a field.
    const bastion = await screen.findByTestId('configure-bastion-login');
    fireEvent.change(bastion, { target: { value: 'user_0000000001' } });

    const save = await screen.findByTestId('configure-save');
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
    expect(api.saveConfig).toHaveBeenCalledWith(expect.objectContaining({
      project_id: 'project-1',
      bastion_username: 'user_0000000001',
    }));
  });


  it('uploads a private key for a registered Chameleon keypair', async () => {
    const settings = mockSettings();
    settings.chameleon = {
      enabled: true,
      ssh_key_file: '',
      sites: {
        'CHI@TACC': {
          auth_type: 'application_credential',
          auth_url: 'https://chi.tacc.chameleoncloud.org:5000/v3',
          app_credential_id: 'app-id',
          app_credential_secret: 'app-credential-fixture',
          project_id: 'project-id',
          default_key_name: 'site-key',
        },
      },
    } as any;
    vi.mocked(api.getSettings).mockResolvedValue(settings as any);
    vi.mocked(api.listChameleonKeypairs).mockResolvedValue([
      { name: 'site-key', fingerprint: 'aa:bb', _site: 'CHI@TACC', has_private_key: false },
    ] as any);

    renderConfigure();

    const tabs = await screen.findAllByTestId('configure-section-tab');
    fireEvent.click(tabs.find(tab => tab.getAttribute('data-section') === 'chameleon')!);

    await screen.findByText('private key missing');
    const keyFile = new File(['test-private-key-placeholder\n'], 'site-key.pem', { type: 'text/plain' });
    fireEvent.change(screen.getByTestId('chameleon-keypair-private-key-CHI@TACC-site-key'), {
      target: { files: [keyFile] },
    });

    await waitFor(() => expect(api.uploadChameleonKeypairPrivateKey).toHaveBeenCalledWith('CHI@TACC', 'site-key', keyFile));
    expect(await screen.findByText('Private key saved')).toBeInTheDocument();
  });

  it('saves a per-site Chameleon default SSH key', async () => {
    const settings = mockSettings();
    settings.chameleon = {
      enabled: true,
      ssh_key_file: '',
      sites: {
        'CHI@TACC': {
          auth_type: 'application_credential',
          auth_url: 'https://chi.tacc.chameleoncloud.org:5000/v3',
          app_credential_id: 'app-id',
          app_credential_secret: 'app-credential-fixture',
          project_id: 'project-id',
          default_key_name: '',
        },
      },
    } as any;
    vi.mocked(api.getSettings).mockResolvedValue(settings as any);
    vi.mocked(api.listChameleonKeypairs).mockResolvedValue([
      { name: 'site-key', _site: 'CHI@TACC' },
      { name: 'loomai-key', _site: 'CHI@TACC' },
    ] as any);

    renderConfigure();

    const tabs = await screen.findAllByTestId('configure-section-tab');
    fireEvent.click(tabs.find(tab => tab.getAttribute('data-section') === 'chameleon')!);

    await waitFor(() => expect(api.listChameleonKeypairs).toHaveBeenCalledWith('CHI@TACC'));
    await screen.findAllByText('site-key');
    fireEvent.change(screen.getByTestId('chameleon-default-key-CHI@TACC'), { target: { value: 'site-key' } });

    const save = await screen.findByTestId('configure-save');
    await waitFor(() => expect(save).not.toBeDisabled());
    fireEvent.click(save);

    await waitFor(() => expect(api.saveSettings).toHaveBeenCalled());
    expect(api.saveSettings).toHaveBeenCalledWith(expect.objectContaining({
      chameleon: expect.objectContaining({
        sites: expect.objectContaining({
          'CHI@TACC': expect.objectContaining({ default_key_name: 'site-key' }),
        }),
      }),
    }));
  });
});
