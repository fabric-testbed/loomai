import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import MCPServersPanel from '../components/MCPServersPanel';
import * as api from '../api/client';
import type { MCPServerInfo } from '../api/client';

vi.mock('../api/client', () => ({
  getMCPServers: vi.fn(),
  getMCPServer: vi.fn(),
  probeMCPServer: vi.fn(),
}));

const metrics: MCPServerInfo = {
  name: 'fabric-metrics',
  label: 'FABRIC Infrastructure Metrics',
  description: 'Live FABRIC testbed infrastructure metrics.',
  transport: 'http',
  url: 'https://infrastructure-metrics-mcp.fabric-testbed.net/mcp',
  auth: 'fabric_token',
  harness: true,
  loomai: true,
  requires_staff: false,
  docs_url: '',
  topics: ['cpu', 'temperature'],
  builtin: true,
  command: [],
  harnesses: ['opencode', 'claude'],
  status: { reachable: true, tool_count: 17, error: '', auth_warning: '', latency_ms: 680 },
};

const harness: MCPServerInfo = {
  ...metrics,
  name: 'loomai-harness',
  label: 'LoomAI Harness (local)',
  transport: 'stdio',
  url: '',
  auth: 'none',
  loomai: false,
  command: ['python3', '-m', 'app.harness_mcp_server'],
  harnesses: ['opencode', 'claude', 'pi'],
  status: { reachable: true, tool_count: 0, error: '', local: true },
};

beforeEach(() => {
  vi.clearAllMocks();
  (api.getMCPServers as ReturnType<typeof vi.fn>).mockResolvedValue({ servers: [metrics, harness] });
});

describe('MCPServersPanel', () => {
  it('lists every registered server', async () => {
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getAllByTestId('mcp-server-card')).toHaveLength(2));
    expect(screen.getByText('FABRIC Infrastructure Metrics')).toBeInTheDocument();
    expect(screen.getByText('LoomAI Harness (local)')).toBeInTheDocument();
  });

  it('shows tool count and latency for a reachable remote server', async () => {
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getByText('17 tools · 680ms')).toBeInTheDocument());
  });

  it('marks the server the assistant can call', async () => {
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getByText('Assistant')).toBeInTheDocument());
  });

  it('shows the harnesses a server is wired into', async () => {
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getAllByText('opencode').length).toBeGreaterThan(0));
    expect(screen.getByText('pi')).toBeInTheDocument();
  });

  it('renders a local stdio server without a probe button', async () => {
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getAllByTestId('mcp-server-card')).toHaveLength(2));
    // Only the HTTP server is probeable.
    expect(screen.getAllByTestId('mcp-probe')).toHaveLength(1);
    expect(screen.getByText('python3 -m app.harness_mcp_server')).toBeInTheDocument();
  });

  it('loads tool details on expand', async () => {
    (api.getMCPServer as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...metrics,
      status: {
        ...metrics.status,
        tools: [{ name: 'fabric_metrics_cpu', description: 'CPU utilization\nmore', input_schema: {} }],
      },
    });
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getByTestId('mcp-toggle-tools')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('mcp-toggle-tools'));
    await waitFor(() => expect(screen.getByText('fabric_metrics_cpu')).toBeInTheDocument());
    // Only the first line of a multi-line description is shown.
    expect(screen.getByText('CPU utilization')).toBeInTheDocument();
  });

  it('surfaces an auth warning distinctly from an outage', async () => {
    (api.getMCPServers as ReturnType<typeof vi.fn>).mockResolvedValue({
      servers: [{ ...metrics, status: { ...metrics.status, auth_warning: 'token too large for header buffer' } }],
    });
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getByTestId('mcp-auth-warning')).toBeInTheDocument());
    expect(screen.getByText(/token too large for header buffer/)).toBeInTheDocument();
    expect(screen.getByTestId('mcp-status')).toHaveTextContent('auth issue');
  });

  it('shows an unreachable server as unreachable', async () => {
    (api.getMCPServers as ReturnType<typeof vi.fn>).mockResolvedValue({
      servers: [{ ...metrics, status: { reachable: false, tool_count: 0, error: 'connection refused' } }],
    });
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getByTestId('mcp-status')).toHaveTextContent('unreachable'));
    expect(screen.getByText('connection refused')).toBeInTheDocument();
  });

  it('re-probes one server on demand', async () => {
    (api.probeMCPServer as ReturnType<typeof vi.fn>).mockResolvedValue({
      reachable: true, tool_count: 17, error: '', latency_ms: 120, tools: [],
    });
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getAllByTestId('mcp-probe')).toHaveLength(1));
    fireEvent.click(screen.getAllByTestId('mcp-probe')[0]);
    await waitFor(() => expect(api.probeMCPServer).toHaveBeenCalledWith('fabric-metrics'));
    await waitFor(() => expect(screen.getByText('17 tools · 120ms')).toBeInTheDocument());
  });

  it('reports a load failure instead of rendering an empty list silently', async () => {
    (api.getMCPServers as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('backend down'));
    render(<MCPServersPanel />);
    await waitFor(() => expect(screen.getByText('backend down')).toBeInTheDocument());
  });
});
