import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';

test.describe('application shell with mocked APIs', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/');
  });

  test('loads the default FABRIC view', async ({ page }) => {
    await expect(page.locator('img[alt="LoomAI"]').first()).toBeVisible();
    await expect(page.getByRole('button', { name: /View FABRIC/ })).toBeVisible();
  });

  test('shows mocked slice data in the FABRIC slice list', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Slices', exact: true })).toBeVisible();
    await expect(page.getByRole('row', { name: /mock-fabric/ })).toBeVisible();
  });
});
