import { expect, test } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import { scenarioNoSlices } from '../fixtures/test-data';

test.describe('FABRIC mocked slice workflow', () => {
  test('creates a draft, adds resources, submits, and deletes without live FABRIC resources', async ({ page }) => {
    const scenario = await mockAllApis(page, scenarioNoSlices());
    const sliceName = 'mock-fabric-workflow';
    const nodeName = 'mock-node';
    const componentName = 'nic1';
    const interfaceName = `${nodeName}-${componentName}-p1`;
    const networkName = 'mock-net';
    const getCreatedSlice = () => (scenario.slices as any[]).find(slice => slice.name === sliceName);

    await page.goto('/');
    await expect(page.getByTestId('fabric-bar')).toBeVisible({ timeout: 10_000 });

    page.once('dialog', async dialog => {
      expect(dialog.message()).toContain('Slice name');
      await dialog.accept(sliceName);
    });
    await page.getByTestId('fabric-bar-new-slice').click();

    await expect(page.getByTestId('fabric-bar-slice-select')).toHaveValue(`${sliceName}-id`);
    await expect(page.locator('[data-testid="fabric-bar-slice-select"] option:checked')).toContainText(sliceName);

    const editor = page.getByTestId('editor-panel');
    await expect(editor).toBeVisible();
    await editor.locator('[data-testid="editor-tab"][data-editor-tab="fabric"]').click();
    await expect(editor.locator('[data-testid="editor-tab-panel"][data-editor-tab-panel="fabric"]')).toBeVisible();

    await editor.getByTestId('add-sliver-button').click();
    await editor.locator('[data-testid="add-sliver-option"][data-sliver-type="node"]').click();
    await editor.getByTestId('node-name-input').fill(nodeName);
    await editor.getByTestId('node-component-model-select').selectOption('NIC_Basic');
    await editor.getByTestId('node-component-name-input').fill(componentName);
    await editor.getByTestId('node-component-add').click();
    await expect(editor.locator(`[data-testid="node-pending-component-row"][data-component-name="${componentName}"]`)).toBeVisible();
    await editor.getByTestId('node-submit').click();

    await expect.poll(() => getCreatedSlice()?.nodes?.length ?? 0).toBe(1);
    await expect.poll(() => getCreatedSlice()?.nodes?.[0]?.name).toBe(nodeName);
    await expect.poll(() => getCreatedSlice()?.nodes?.[0]?.interfaces?.[0]?.name).toBe(interfaceName);
    await expect(editor.getByTestId('sliver-selector')).toContainText(nodeName);

    await editor.getByTestId('add-sliver-button').click();
    await editor.locator('[data-testid="add-sliver-option"][data-sliver-type="l2network"]').click();
    await editor.getByTestId('network-name-input').fill(networkName);
    await editor.getByTestId('network-interfaces-select').selectOption([interfaceName]);
    await editor.getByTestId('network-submit').click();

    await expect.poll(() => getCreatedSlice()?.networks?.length ?? 0).toBe(1);
    await expect.poll(() => getCreatedSlice()?.networks?.[0]?.name).toBe(networkName);
    await expect.poll(() => getCreatedSlice()?.networks?.[0]?.interfaces?.[0]?.name).toBe(interfaceName);
    await expect(editor.getByTestId('sliver-selector')).toContainText(networkName);

    await page.getByTestId('fabric-bar-submit-slice').click();

    await expect.poll(() => getCreatedSlice()?.state).toBe('StableOK');
    await expect(page.locator('[data-testid="fabric-bar-slice-select"] option:checked')).toContainText('StableOK');

    page.once('dialog', async dialog => {
      expect(dialog.message()).toContain(sliceName);
      await dialog.accept();
    });
    await page.getByTestId('fabric-bar-delete-slice').click();

    await expect.poll(() => getCreatedSlice()?.state).toBe('Dead');
    await expect(page.getByTestId('fabric-bar-slice-select')).toHaveValue('');
  });
});
