import { test, expect } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import { makeSliceData } from '../fixtures/test-data';

test.describe('Slice Lifecycle', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
  });

  test('create a new slice', async ({ page }) => {
    const sliceData = makeSliceData('my-test-slice', 'draft-1111');

    // Mock create endpoint
    await page.route('**/api/slices?*', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ json: sliceData });
      }
      return route.fallback();
    });

    // Mock get endpoint for the new slice
    await page.route('**/api/slices/draft-1111', (route) =>
      route.fulfill({ json: sliceData })
    );

    await page.goto('/');

    // Navigate to slices view
    await page.locator('.landing-tile', { hasText: 'Slices' }).click();
    await expect(page.locator('.toolbar-btn-new')).toBeVisible();

    // Click "New" button
    await page.locator('.toolbar-btn-new').click();

    // Fill in slice name in modal
    await expect(page.locator('.toolbar-modal')).toBeVisible();
    await page.locator('.toolbar-modal-input').fill('my-test-slice');
    await page.locator('.toolbar-modal button.success').click();

    // Slice should be created — selector should show the name
    await expect(page.locator('.slice-combo-input')).toHaveValue('my-test-slice');
  });

  test('delete a slice', async ({ page }) => {
    const sliceData = makeSliceData('to-delete', 'draft-2222');

    // Start with one slice in the list
    await page.route('**/api/slices', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          json: [{ name: 'to-delete', id: 'draft-2222', state: 'Draft' }],
        });
      }
      return route.fallback();
    });

    await page.route('**/api/slices/draft-2222', (route) => {
      if (route.request().method() === 'DELETE') {
        return route.fulfill({ json: { status: 'deleted' } });
      }
      return route.fulfill({ json: sliceData });
    });

    await page.goto('/');
    await page.locator('.landing-tile', { hasText: 'Slices' }).click();

    // Select the slice from combo
    await page.locator('.slice-combo-toggle').click();
    await page.locator('.slice-combo-option', { hasText: 'to-delete' }).click();

    // Click delete
    await page.locator('.toolbar-btn-delete').click();

    // Confirm deletion in modal
    await expect(page.locator('.toolbar-modal')).toBeVisible();
    await page.locator('.toolbar-modal button.danger').click();
  });
});
