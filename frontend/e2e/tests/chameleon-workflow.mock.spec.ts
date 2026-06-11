import { expect, test } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import { makeChameleonLease, scenarioNoSlices } from '../fixtures/test-data';

test.describe('Chameleon mocked slice workflow', () => {
  test('creates a draft, adds resources, verifies graph state, detaches resources, and deletes without live Chameleon resources', async ({ page }) => {
    const sliceName = 'mock-chi-workflow';
    const leaseName = 'mock-chi-lease';
    const nodeName = 'node1';
    const networkName = 'mock-chi-net';
    const draftId = `${sliceName}-id`;
    const scenario = await mockAllApis(page, scenarioNoSlices({
      chameleonLeases: [makeChameleonLease(leaseName, 'CHI@UC')],
      chameleonInstances: [],
      chameleonNetworks: [],
    }));
    const getDraft = () => (scenario.chameleonSlices as any[]).find(slice => slice.name === sliceName);

    await page.goto('/');
    await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
    await page.locator('.title-pill-option', { hasText: /^Chameleon$/ }).click();
    await expect(page.getByTestId('chameleon-bar')).toBeVisible({ timeout: 10_000 });

    page.once('dialog', async dialog => {
      expect(dialog.message()).toContain('Draft name');
      await dialog.accept(sliceName);
    });
    await page.getByTestId('chameleon-bar-new-draft').click();

    await expect(page.getByTestId('chameleon-bar-slice-select')).toHaveValue(`${sliceName}-id`);
    await expect(page.locator('[data-testid="chameleon-bar-slice-select"] option:checked')).toContainText(sliceName);

    const editor = page.getByTestId('chameleon-editor');
    await expect(editor).toBeVisible();
    await editor.locator('[data-testid="chameleon-editor-tab"][data-chameleon-tab="servers"]').click();
    await expect(editor.getByTestId('chameleon-add-server')).toBeEnabled({ timeout: 10_000 });
    await editor.getByTestId('chameleon-add-server').click();

    await expect.poll(() => getDraft()?.nodes?.length ?? 0).toBe(1);
    await expect.poll(() => getDraft()?.nodes?.[0]?.name).toBe(nodeName);
    await expect(editor.locator(`[data-testid="chameleon-planned-server-row"][data-node-name="${nodeName}"]`)).toBeVisible();

    await editor.locator('[data-testid="chameleon-editor-tab"][data-chameleon-tab="ips"]').click();
    const ipIntentRow = editor.locator(`[data-testid="chameleon-floating-ip-intent-row"][data-node-name="${nodeName}"]`);
    await expect(ipIntentRow).toBeVisible();
    await ipIntentRow.locator('select').selectOption('0');
    await expect.poll(() => getDraft()?.floating_ips ?? []).toEqual([{ node_id: `${nodeName}-id`, nic: 0 }]);

    await editor.locator('[data-testid="chameleon-editor-tab"][data-chameleon-tab="networks"]').click();
    await editor.getByTestId('chameleon-draft-network-name').fill(networkName);
    await editor.locator(`[data-testid="chameleon-draft-network-node-option"][data-node-name="${nodeName}"] input`).check();
    await editor.getByTestId('chameleon-add-draft-network').click();

    await expect.poll(() => getDraft()?.networks?.length ?? 0).toBe(1);
    await expect.poll(() => getDraft()?.networks?.[0]?.connected_nodes ?? []).toContain(`${nodeName}-id`);
    const networkRow = editor.locator(`[data-testid="chameleon-draft-network-row"][data-network-name="${networkName}"]`);
    await expect(networkRow).toBeVisible();

    const graph = await page.evaluate(async (id) => fetch(`/api/chameleon/drafts/${id}/graph`).then(response => response.json()), draftId);
    expect(graph.nodes.some((node: any) => node.data?.id === `node-${nodeName}-id`)).toBe(true);
    expect(graph.nodes.some((node: any) => node.data?.id === `network-${networkName}-id`)).toBe(true);
    expect(graph.edges.some((edge: any) => (
      edge.data?.source === `node-${nodeName}-id` && edge.data?.target === `network-${networkName}-id`
    ))).toBe(true);

    const deleteNetworkResult = await page.evaluate(async ({ id, networkId }) => {
      const response = await fetch(`/api/chameleon/drafts/${id}/networks/${networkId}`, { method: 'DELETE' });
      return { ok: response.ok, body: await response.json() };
    }, { id: draftId, networkId: `${networkName}-id` });
    expect(deleteNetworkResult.ok).toBe(true);
    expect(deleteNetworkResult.body.networks).toHaveLength(0);

    await expect.poll(() => getDraft()?.networks?.length ?? 0).toBe(0);
    const graphAfterDetach = await page.evaluate(async (id) => fetch(`/api/chameleon/drafts/${id}/graph`).then(response => response.json()), draftId);
    expect(graphAfterDetach.nodes.some((node: any) => node.data?.id === `network-${networkName}-id`)).toBe(false);
    expect(graphAfterDetach.edges).toHaveLength(0);

    await page.getByTestId('chameleon-bar-refresh-slices').click();
    await page.locator('[data-testid="chameleon-bar-tab"][data-chameleon-bar-tab="slices"]').click();
    const sliceRow = page.locator(`[data-testid="chameleon-slice-row"][data-slice-name="${sliceName}"]`);
    await expect(sliceRow).toBeVisible();
    await page.getByLabel(`Expand ${sliceName}`).click();
    await page.getByTestId('chameleon-add-lease').click();

    const modal = page.getByTestId('chameleon-lease-modal');
    await expect(modal).toBeVisible();
    await modal.getByLabel('Filter candidate Chameleon leases').fill(leaseName);
    const candidate = modal.locator(`[data-testid="chameleon-lease-candidate"][data-lease-name="${leaseName}"]`);
    await expect(candidate).toHaveAttribute('data-membership', 'available');
    await candidate.getByTestId('chameleon-lease-toggle').click();

    await expect.poll(() => getDraft()?.resources?.filter((resource: any) => resource.type === 'lease').length ?? 0).toBe(1);
    await expect(candidate).toHaveAttribute('data-membership', 'attached');
    await candidate.getByTestId('chameleon-lease-toggle').click();

    await expect.poll(() => getDraft()?.resources?.filter((resource: any) => resource.type === 'lease').length ?? 0).toBe(0);
    await expect(candidate).toHaveAttribute('data-membership', 'available');
    await modal.getByTestId('chameleon-lease-modal-close').click();
    await expect(modal).toBeHidden();

    page.once('dialog', async dialog => {
      expect(dialog.message()).toContain(`Delete draft "${sliceName}"`);
      await dialog.accept();
    });
    await page.getByTestId('chameleon-bar-delete-draft').click();

    await expect(page.getByTestId('chameleon-bar-slice-select')).toHaveValue('');
    await expect.poll(() => getDraft()).toBeUndefined();
  });
});
