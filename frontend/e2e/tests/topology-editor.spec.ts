import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import { makeSliceData, makeNode, makeNetwork } from '../fixtures/test-data';

test.describe('Topology Editor', () => {
  const sliceId = 'draft-topo-1';

  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);

    const baseSlice = makeSliceData('topo-test', sliceId);
    let currentSlice = { ...baseSlice };

    // Mock create
    await page.route('**/api/slices?*', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ json: currentSlice });
      }
      return route.fallback();
    });

    // Mock get
    await page.route(`**/api/slices/${sliceId}`, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: currentSlice });
      }
      return route.fallback();
    });

    // Mock add node
    await page.route(`**/api/slices/${sliceId}/nodes`, (route) => {
      if (route.request().method() === 'POST') {
        const node1 = makeNode('node1', 'RENC');
        currentSlice = makeSliceData('topo-test', sliceId, {
          nodes: [node1],
        });
        return route.fulfill({ json: currentSlice });
      }
      return route.fallback();
    });

    // Mock add network
    await page.route(`**/api/slices/${sliceId}/networks`, (route) => {
      if (route.request().method() === 'POST') {
        const net = makeNetwork('lan1', 'L2Bridge');
        currentSlice = {
          ...currentSlice,
          networks: [...currentSlice.networks, net],
        };
        return route.fulfill({ json: currentSlice });
      }
      return route.fallback();
    });

    // Mock validate
    await page.route(`**/api/slices/${sliceId}/validate`, (route) =>
      route.fulfill({
        json: { valid: true, issues: [] },
      })
    );

    // Navigate to slices view and create a slice
    await page.goto('/');
    await page.locator('.landing-tile', { hasText: 'Slices' }).click();
    await page.locator('.toolbar-btn-new').click();
    await page.locator('.toolbar-modal-input').fill('topo-test');
    await page.locator('.toolbar-modal button.success').click();
    await expect(page.locator('.slice-combo-input')).toHaveValue('topo-test');
  });

  test('add a VM node via editor menu', async ({ page }) => {
    // Switch to Slivers tab where the add button lives
    await page.locator('button', { hasText: 'Slivers' }).first().click();

    // Click the add sliver button
    await page.locator('.add-sliver-btn').click();
    await expect(page.locator('.add-sliver-menu')).toBeVisible();

    // Click "VM Node"
    await page.locator('.add-sliver-item', { hasText: 'VM Node' }).click();
  });

  test('add a network via editor menu', async ({ page }) => {
    // Switch to Slivers tab
    await page.locator('button', { hasText: 'Slivers' }).first().click();

    await page.locator('.add-sliver-btn').click();
    await expect(page.locator('.add-sliver-menu')).toBeVisible();
    await page.locator('.add-sliver-item', { hasText: 'Network (L2)' }).click();
  });
});
