import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import FileTransferView from '../components/FileTransferView';
import * as api from '../api/client';

vi.mock('../components/FileEditor', () => ({
  default: ({ filePath }: { filePath: string }) => <div data-testid="file-editor">{filePath}</div>,
  isTextFile: (name: string) => name.endsWith('.txt') || name.endsWith('.md'),
  isLikelyBinary: () => false,
}));

vi.mock('../api/client', () => ({
  listFiles: vi.fn(),
  createFolder: vi.fn(),
  deleteFile: vi.fn(),
  uploadFiles: vi.fn(),
  uploadFilesWithPaths: vi.fn(),
  downloadFile: vi.fn(),
  downloadFolder: vi.fn(),
  readFileContent: vi.fn(),
  writeFileContent: vi.fn(),
  listVmFiles: vi.fn(),
  vmMkdir: vi.fn(),
  vmDelete: vi.fn(),
  uploadDirectToVm: vi.fn(),
  uploadDirectToVmWithPaths: vi.fn(),
  downloadDirectFromVm: vi.fn(),
  downloadFolderFromVm: vi.fn(),
  executeOnVm: vi.fn(),
  readVmFileContent: vi.fn(),
  writeVmFileContent: vi.fn(),
  listChameleonInstanceFiles: vi.fn(),
  chameleonMkdir: vi.fn(),
  chameleonDelete: vi.fn(),
  uploadDirectToChameleonInstance: vi.fn(),
  uploadDirectToChameleonInstanceWithPaths: vi.fn(),
  downloadDirectFromChameleonInstance: vi.fn(),
  downloadFolderFromChameleonInstance: vi.fn(),
  executeOnChameleonInstance: vi.fn(),
  readChameleonFileContent: vi.fn(),
  writeChameleonFileContent: vi.fn(),
}));

const sliceData = {
  name: 'slice-a',
  id: 'slice-a',
  state: 'StableOK',
  dirty: false,
  lease_start: '',
  lease_end: '',
  error_messages: [],
  nodes: [{ name: 'node1', site: 'RENC', username: 'ubuntu', components: [], interfaces: [] }],
  networks: [],
  facility_ports: [],
  port_mirrors: [],
  graph: { nodes: [], edges: [] },
};

describe('FileTransferView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.listFiles).mockResolvedValue([
      { name: 'README.md', path: '/home/fabric/work/README.md', type: 'file', size: 128, modified: 0 },
      { name: 'experiments', path: '/home/fabric/work/experiments', type: 'dir', size: 0, modified: 0 },
    ] as any);
    vi.mocked(api.listVmFiles).mockResolvedValue([
      { name: 'vm-readme.txt', path: '/home/ubuntu/vm-readme.txt', type: 'file', size: 64, modified: 0 },
    ] as any);
    vi.mocked(api.createFolder).mockResolvedValue({ created: 'new-local' });
    vi.mocked(api.vmMkdir).mockResolvedValue({ created: '/home/ubuntu/new-vm' });
    vi.mocked(api.vmDelete).mockResolvedValue({ deleted: '/home/ubuntu/vm-readme.txt' });
  });

  it('loads local and VM file tables and creates folders on both sides', async () => {
    render(<FileTransferView sliceName="slice-a" sliceData={sliceData as any} />);

    expect(await screen.findByTestId('file-transfer-view')).toBeInTheDocument();
    expect(await screen.findByText('README.md')).toBeInTheDocument();
    expect(await screen.findByText('vm-readme.txt')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('local-new-folder'));
    fireEvent.change(screen.getByPlaceholderText('Folder name...'), { target: { value: 'new-local' } });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => expect(api.createFolder).toHaveBeenCalledWith('', 'new-local'));

    fireEvent.click(screen.getByTestId('vm-new-folder'));
    fireEvent.change(screen.getByPlaceholderText('Folder name...'), { target: { value: 'new-vm' } });
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));

    await waitFor(() => expect(api.vmMkdir).toHaveBeenCalledWith('slice-a', 'node1', '/home/ubuntu/new-vm'));
  });

  it('builds a unified selector for federated FABRIC and Chameleon members', async () => {
    render(
      <FileTransferView
        sliceName=""
        sliceData={null}
        fabricSlices={[{ sliceName: 'fabric-member', sliceData: sliceData as any }]}
        chameleonInstances={[{ instance_id: 'chi-inst-1', site: 'CHI@TACC', name: 'chi-node' }]}
      />,
    );

    const select = await screen.findByTestId('vm-node-select');
    expect(within(select).getByRole('option', { name: /node1.*fabric-member/ })).toBeInTheDocument();
    expect(within(select).getByRole('option', { name: /chi-node.*Chameleon/ })).toBeInTheDocument();
  });

  it('shows local file loading errors without hiding the transfer surface', async () => {
    vi.mocked(api.listFiles).mockRejectedValueOnce(new Error('Local file API unavailable'));

    render(<FileTransferView sliceName="slice-a" sliceData={sliceData as any} />);

    expect(await screen.findByTestId('file-transfer-view')).toBeInTheDocument();
    expect(await screen.findByText('Local file API unavailable')).toBeInTheDocument();
    expect(await screen.findByTestId('vm-node-select')).toBeInTheDocument();
  });
});
