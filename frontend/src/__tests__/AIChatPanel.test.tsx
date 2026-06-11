import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import AIChatPanel from '../components/AIChatPanel';
import * as api from '../api/client';

vi.mock('../api/client', () => ({
  getConfig: vi.fn(),
  getDefaultModel: vi.fn(),
  getAiModels: vi.fn(),
  getChatAgents: vi.fn(),
  setDefaultModel: vi.fn(),
  refreshAiModels: vi.fn(),
  streamChat: vi.fn(),
  stopChatStream: vi.fn(),
}));

const modelsResponse = {
  default: 'fabric/mock-model',
  fabric: [
    { id: 'fabric/mock-model', name: 'fabric/mock-model', healthy: true, context_length: 128000, tier: 'large', supports_tools: true },
    { id: 'fabric/other-model', name: 'fabric/other-model', healthy: true, context_length: 32000, tier: 'standard', supports_tools: true },
  ],
  nrp: [{ id: 'nrp/mock-model', name: 'nrp/mock-model', healthy: true, context_length: 64000, tier: 'standard', supports_tools: true }],
  custom: {},
  has_key: { fabric: true, nrp: true },
  models: ['fabric/mock-model', 'fabric/other-model'],
  nrp_models: ['nrp/mock-model'],
};

async function* mockChatStream() {
  yield { content: 'Mock assistant response.' };
  yield { done: true };
}

describe('AIChatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
    vi.mocked(api.getConfig).mockResolvedValue({ ai_api_key_set: true } as any);
    vi.mocked(api.getDefaultModel).mockResolvedValue({ default: 'fabric/mock-model', source: 'fabric' });
    vi.mocked(api.getAiModels).mockResolvedValue(modelsResponse as any);
    vi.mocked(api.getChatAgents).mockResolvedValue([{ id: 'default', name: 'Default', description: 'Default assistant' }]);
    vi.mocked(api.setDefaultModel).mockResolvedValue({ default: 'fabric/other-model', source: 'fabric' });
    vi.mocked(api.refreshAiModels).mockResolvedValue({ ...modelsResponse, added: 0, removed: 0, updated: 0, message: 'Models up to date' } as any);
    vi.mocked(api.streamChat).mockImplementation(mockChatStream as any);
    vi.mocked(api.stopChatStream).mockResolvedValue({ status: 'stopped' });
  });

  it('loads model choices and persists model selection', async () => {
    render(<AIChatPanel onCollapse={() => {}} />);

    const select = await screen.findByTestId('ai-chat-model-select');
    await waitFor(() => expect(select).toHaveValue('fabric/mock-model'));

    fireEvent.change(select, { target: { value: 'fabric/other-model' } });

    expect(api.setDefaultModel).toHaveBeenCalledWith('fabric/other-model');
    expect(localStorage.getItem('loomai-chat-selected-model')).toBe('fabric/other-model');
  });

  it('sends chat prompts through the streaming API', async () => {
    render(<AIChatPanel onCollapse={() => {}} />);

    const input = await screen.findByTestId('ai-chat-input');
    fireEvent.change(input, { target: { value: 'Summarize my slice' } });
    fireEvent.click(screen.getByTestId('ai-chat-send'));

    await waitFor(() => expect(api.streamChat).toHaveBeenCalled());
    expect(await screen.findByText('Summarize my slice')).toBeInTheDocument();
    expect(await screen.findByText('Mock assistant response.')).toBeInTheDocument();
  });

  it('refreshes model metadata from the shared AI controls', async () => {
    render(<AIChatPanel onCollapse={() => {}} />);

    await screen.findByTestId('ai-chat-model-select');
    fireEvent.click(screen.getByTestId('ai-chat-refresh-models'));

    await waitFor(() => expect(api.refreshAiModels).toHaveBeenCalled());
    await waitFor(() => expect(api.getAiModels).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Models up to date')).toBeInTheDocument();
  });
});
