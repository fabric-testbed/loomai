import { ApiError, apiError, deleteSlice, getSlice } from '../api/client';

function response(status: number, body: string, ok = false): Response {
  return {
    ok,
    status,
    text: async () => body,
    json: async () => JSON.parse(body),
  } as unknown as Response;
}

describe('ApiError', () => {
  it('uses detail.message and keeps code/status/body', async () => {
    const err = await apiError(response(422, JSON.stringify({
      detail: { code: 'LEASE_ALREADY_EXCEEDS_POLICY', message: 'Nothing to renew.' },
    })));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe('Nothing to renew.');
    expect(err.code).toBe('LEASE_ALREADY_EXCEEDS_POLICY');
    expect(err.status).toBe(422);
    expect(err.body).toContain('LEASE_ALREADY_EXCEEDS_POLICY');
    expect(err.message).not.toContain('{');
  });

  it('uses a string detail', () => {
    expect(new ApiError(404, '{"detail":"Slice not found: x"}').message).toBe('Slice not found: x');
  });

  it('joins FastAPI validation errors', () => {
    const err = new ApiError(422, JSON.stringify({ detail: [
      { loc: ['body', 'name'], msg: 'Field required', type: 'missing' },
      { loc: ['body', 'site'], msg: 'Invalid site', type: 'value_error' },
    ] }));
    expect(err.message).toBe('Field required; Invalid site');
  });

  it('falls back to the body text or a status message', () => {
    expect(new ApiError(502, 'Bad Gateway').message).toBe('Bad Gateway');
    expect(new ApiError(500, '').message).toBe('Request failed with status 500');
  });

  it('is what fetchJson throws', async () => {
    const fetchMock = vi.fn(async () => response(400, '{"detail":{"message":"bad site"}}'));
    vi.stubGlobal('fetch', fetchMock);
    try {
      await expect(getSlice('x')).rejects.toMatchObject({ name: 'ApiError', status: 400, message: 'bad site' });
      await expect(deleteSlice('x')).rejects.toBeInstanceOf(ApiError);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
