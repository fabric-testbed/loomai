import { expect, test } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import {
  configStatus,
  makeArtifact,
  makeDefaultApiScenario,
  makeFileEntry,
  makeRemoteArtifact,
} from '../fixtures/test-data';

async function openTopView(page: import('@playwright/test').Page, label: RegExp | string) {
  await page.locator('[data-help-id="titlebar.view"] .title-pill').click();
  await page.locator('.title-pill-dropdown').getByRole('button', { name: label }).click();
}

test.describe('shared WebUI surfaces with mocked APIs', () => {
  test('opens settings, runs checks, and keeps section navigation testable', async ({ page }) => {
    await mockAllApis(page, makeDefaultApiScenario());
    await page.goto('/');

    // Settings now lives inside the title-user menu — open it first.
    await page.locator('[data-help-id="titlebar.user"]').click();
    await page.locator('[data-help-id="titlebar.settings"]').click();
    await expect(page.getByTestId('configure-view')).toBeVisible();

    await page.getByTestId('configure-test-all').click();
    await expect(page.getByText('Mock token check passed')).toBeVisible();

    await page.locator('[data-testid="configure-section-tab"][data-section="storage"]').click();
    await expect(page.getByText('Storage Paths')).toBeVisible();
  });

  test('browses local and marketplace artifacts and creates a blank artifact', async ({ page }) => {
    const scenario = await mockAllApis(page, {
      artifacts: [makeArtifact('Local Harness Artifact')],
      remoteArtifacts: [makeRemoteArtifact('Remote Harness Artifact')],
    } as any);
    await page.goto('/');

    await openTopView(page, /Marketplace/);
    await expect(page.getByTestId('libraries-view')).toBeVisible();
    await expect(page.getByTestId('library-artifact-card')).toHaveAttribute('data-dir-name', 'Local_Harness_Artifact');

    await page.getByRole('button', { name: '+ New Artifact' }).click();
    await page.getByPlaceholder('Artifact name...').fill('Browser Harness Artifact');
    await page.getByPlaceholder('Description (optional)...').fill('Created by mocked E2E');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect.poll(() => (scenario.artifacts as any[]).some(artifact => artifact.dir_name === 'Browser_Harness_Artifact')).toBe(true);
    await expect(page.getByText('Browser_Harness_Artifact')).toBeVisible();
    await page.getByRole('button', { name: '← Back' }).click();

    await page.getByRole('button', { name: /FABRIC Marketplace/ }).click();
    const remoteCard = page.getByTestId('library-marketplace-card');
    await expect(remoteCard).toHaveAttribute('data-artifact-uuid', 'remote-harness-artifact-uuid');
    await expect(remoteCard.locator('.tv-card-name')).toHaveText('Remote Harness Artifact');
  });

  test('opens FABRIC storage and exercises the file-transfer harness', async ({ page }) => {
    const scenario = await mockAllApis(page, {
      files: [makeFileEntry('README.md'), makeFileEntry('experiments', 'dir')],
      vmFiles: [makeFileEntry('vm-readme.txt')],
    } as any);
    await page.goto('/');

    await openTopView(page, /FABRIC/);
    await expect(page.getByTestId('fabric-bar')).toBeVisible();
    await page.getByTestId('fabric-bar-slice-select').selectOption('mock-fabric-id');
    await page.locator('[data-testid="fabric-bar-tab"][data-tab="storage"]').click();

    await expect(page.getByTestId('file-transfer-view')).toBeVisible();
    await expect(page.getByTestId('local-file-row').filter({ hasText: 'README.md' })).toBeVisible();
    await expect(page.getByTestId('vm-file-row').filter({ hasText: 'vm-readme.txt' })).toBeVisible();

    await page.getByTestId('local-new-folder').click();
    await page.getByPlaceholder('Folder name...').fill('e2e-folder');
    await page.getByRole('button', { name: 'OK' }).click();
    await expect.poll(() => (scenario.files as any[]).some(entry => entry.name === 'e2e-folder')).toBe(true);
  });

  test('opens LoomAI chat, switches models, and streams a mocked response', async ({ page }) => {
    const scenario = makeDefaultApiScenario({
      configStatus: { ...configStatus, ai_api_key_set: true },
    });
    await mockAllApis(page, scenario);
    await page.goto('/');

    await openTopView(page, /LoomAI/);
    await expect(page.getByTestId('ai-chat-model-select')).toBeVisible();
    await page.getByTestId('ai-chat-model-select').selectOption('fabric/mock-model');

    await page.getByTestId('ai-chat-input').fill('Summarize this mocked test');
    await page.getByTestId('ai-chat-send').click();

    await expect(page.getByText('Summarize this mocked test')).toBeVisible();
    await expect(page.getByText('Mock assistant response.')).toBeVisible();
  });
});
