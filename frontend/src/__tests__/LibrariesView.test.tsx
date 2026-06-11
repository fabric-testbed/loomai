import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import LibrariesView from '../components/LibrariesView';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  getMyArtifacts: vi.fn(),
  listRemoteArtifacts: vi.fn(),
  refreshRemoteArtifacts: vi.fn(),
  createBlankArtifact: vi.fn(),
  loadTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  deleteVmTemplate: vi.fn(),
  deleteExperiment: vi.fn(),
  downloadArtifact: vi.fn(),
  getPublishInfo: vi.fn(),
  listValidTags: vi.fn(),
  listUserProjects: vi.fn(),
  publishArtifact: vi.fn(),
  updateLocalArtifactMetadata: vi.fn(),
  updateRemoteArtifact: vi.fn(),
  deleteRemoteArtifact: vi.fn(),
  uploadArtifactVersion: vi.fn(),
  revertArtifact: vi.fn(),
  deleteArtifactVersion: vi.fn(),
  searchPeople: vi.fn(),
  listTroviArtifacts: vi.fn(),
  downloadTroviArtifact: vi.fn(),
}));

const localArtifact = {
  name: 'Mock Artifact',
  description: 'Local artifact',
  description_short: 'Local artifact',
  source: 'local',
  created: '2026-06-08T12:00:00Z',
  tags: ['mock'],
  category: 'weave',
  dir_name: 'Mock_Artifact',
  is_from_marketplace: false,
  remote_status: 'not_linked',
  is_author: false,
  remote_artifact: null,
};

const remoteArtifact = {
  uuid: 'remote-artifact-uuid',
  title: 'Remote Artifact',
  description_short: 'Remote artifact',
  description_long: 'Remote artifact',
  visibility: 'public',
  tags: ['mock', 'weave'],
  category: 'weave',
  authors: [{ name: 'Test User', affiliation: 'FABRIC' }],
  versions: [{ uuid: 'version-1', version: '1.0.0', urn: 'urn:mock', active: true, created: '2026-06-08T12:00:00Z', version_downloads: 2 }],
  artifact_views: 10,
  artifact_downloads_active: 2,
  number_of_versions: 1,
  created: '2026-06-08T12:00:00Z',
  modified: '2026-06-08T12:00:00Z',
};

function renderLibraries(onEditArtifact = vi.fn()) {
  render(
    <LibrariesView
      onLoadSlice={() => {}}
      onEditArtifact={onEditArtifact}
      chameleonEnabled={false}
    />,
  );
  return onEditArtifact;
}

describe('LibrariesView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getMyArtifacts).mockResolvedValue({
      local_artifacts: [localArtifact],
      authored_remote_only: [],
      user_email: 'test@example.com',
    } as any);
    vi.mocked(api.listRemoteArtifacts).mockResolvedValue({
      artifacts: [remoteArtifact],
      total_count: 1,
      tags: [{ name: 'mock', count: 1 }],
    } as any);
    vi.mocked(api.refreshRemoteArtifacts).mockResolvedValue({
      artifacts: [remoteArtifact],
      total_count: 1,
      tags: [{ name: 'mock', count: 1 }],
    } as any);
    vi.mocked(api.createBlankArtifact).mockResolvedValue({ dir_name: 'New_Artifact' });
    vi.mocked(api.getPublishInfo).mockResolvedValue({ can_update: false, can_fork: false, is_author: false, artifact_uuid: null, remote_title: null });
    vi.mocked(api.listValidTags).mockResolvedValue({ tags: [{ tag: 'mock', restricted: false }] });
    vi.mocked(api.listUserProjects).mockResolvedValue({ projects: [], active_project_id: '' });
  });

  it('loads local artifacts and creates a blank artifact', async () => {
    const onEditArtifact = renderLibraries();

    expect(await screen.findByTestId('libraries-view')).toBeInTheDocument();
    expect(await screen.findByTestId('library-artifact-card')).toHaveAttribute('data-dir-name', 'Mock_Artifact');

    fireEvent.click(screen.getByRole('button', { name: '+ New Artifact' }));
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Artifact name...'), { target: { value: 'New Artifact' } });
    fireEvent.change(screen.getByPlaceholderText('Description (optional)...'), { target: { value: 'Created in test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(api.createBlankArtifact).toHaveBeenCalledWith({
      name: 'New Artifact',
      description: 'Created in test',
    }));
    expect(onEditArtifact).toHaveBeenCalledWith('New_Artifact');
  });

  it('loads marketplace artifacts on demand', async () => {
    renderLibraries();

    fireEvent.click(await screen.findByRole('button', { name: /FABRIC Marketplace/ }));

    await waitFor(() => expect(api.listRemoteArtifacts).toHaveBeenCalled());
    expect(await screen.findByTestId('library-marketplace-card')).toHaveAttribute('data-artifact-uuid', 'remote-artifact-uuid');
    expect(screen.getByText('Remote Artifact')).toBeInTheDocument();
  });
});
