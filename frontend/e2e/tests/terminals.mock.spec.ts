import { expect, test, type Page, type Route } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

/**
 * Persistent terminals across reload (mocked control plane).
 *
 * Today's terminal store maps a frontend tab id -> a backend (server-held)
 * session id in localStorage. On reload it reuses that mapping by minting a
 * fresh attach ticket instead of spawning a new shell. We mock the
 * /api/terminals control plane in-memory and assert:
 *   - first open creates exactly one backend session and records the mapping
 *   - after a full page reload, reopening the tab REUSES the same session id
 *     (a ticket is minted; no second create)
 *
 * The data-plane WebSocket is intentionally not exercised — Playwright can't
 * mock WS here, and that path is covered by backend tests. The store keeps
 * retrying the (failing) socket, which is fine: `create` is gated by the stored
 * id, so it stays at exactly one regardless of reconnects.
 */

interface TermStore {
  creates: number;
  tickets: string[];
  sessions: { id: string; type: string; label: string; created: number }[];
}

async function mockTerminals(page: Page): Promise<TermStore> {
  const store: TermStore = { creates: 0, tickets: [], sessions: [] };
  // Registered AFTER mockAllApis so this LIFO handler wins for /api/terminals*.
  await page.route('**/api/terminals**', async (route: Route) => {
    const req = route.request();
    const { pathname } = new URL(req.url());
    const parts = pathname.split('/').filter(Boolean); // ['api','terminals', id?, 'ticket'?]
    const id = parts[2];
    const isTicket = parts[3] === 'ticket';
    const method = req.method();
    const json = (status: number, body: unknown) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

    if (method === 'POST' && !id) {
      store.creates += 1;
      const meta = {
        id: `mock-term-${store.creates}`,
        type: 'local',
        label: 'Local',
        created: 1000 + store.creates,
        ticket: `mock-term-${store.creates}.tkt`,
      };
      store.sessions.push({ id: meta.id, type: meta.type, label: meta.label, created: meta.created });
      return json(200, meta);
    }
    if (method === 'POST' && id && isTicket) {
      if (!store.sessions.some((s) => s.id === id)) return json(404, { detail: 'no such session' });
      store.tickets.push(id);
      return json(200, { id, ticket: `${id}.tkt${store.tickets.length}` });
    }
    if (method === 'GET' && !id) {
      return json(200, store.sessions);
    }
    if (method === 'DELETE' && id) {
      store.sessions = store.sessions.filter((s) => s.id !== id);
      return json(200, { ok: true });
    }
    return json(404, { detail: 'unhandled' });
  });
  return store;
}

async function openLocalTerminal(page: Page) {
  const tab = page.locator('[data-help-id="bottom.local-terminal"]').first();
  await expect(tab).toBeVisible({ timeout: 15000 });
  await tab.click();
}

test.describe('persistent terminals (mocked)', () => {
  test('local terminal reuses its backend session across reload', async ({ page }) => {
    await mockAllApis(page, {});
    const store = await mockTerminals(page);
    // Start with the bottom console expanded so the Local tab is reachable.
    await page.addInitScript(() => {
      try {
        localStorage.setItem('fabric-console-expanded', '1');
      } catch {
        /* ignore */
      }
    });

    // --- first open: one backend session, mapping persisted ---
    await page.goto('/');
    await openLocalTerminal(page);

    await expect.poll(() => store.creates, { timeout: 15000 }).toBe(1);
    const firstId = await page.evaluate(() =>
      localStorage.getItem('loomai.term.session.local-terminal'),
    );
    expect(firstId).toBe('mock-term-1');

    // --- reload: reattach to the SAME session, no second create ---
    await page.reload();
    await openLocalTerminal(page);

    await expect
      .poll(() => store.tickets.includes('mock-term-1'), { timeout: 15000 })
      .toBe(true);
    expect(store.creates).toBe(1); // crucially NOT 2 — the session was reused
    const secondId = await page.evaluate(() =>
      localStorage.getItem('loomai.term.session.local-terminal'),
    );
    expect(secondId).toBe('mock-term-1');
  });
});
