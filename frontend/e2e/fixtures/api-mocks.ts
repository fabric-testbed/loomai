/** Reusable API route interceptors for Playwright tests. */

import { Page, Route } from '@playwright/test';
import {
  healthResponse,
  configStatus,
  emptySliceList,
  sitesList,
  componentModels,
  imageList,
  templatesList,
  vmTemplatesList,
} from './test-data';

type MockOverrides = {
  slices?: unknown[];
  sites?: unknown[];
  templates?: unknown[];
  vmTemplates?: unknown[];
  configStatus?: unknown;
  health?: unknown;
};

/**
 * Set up standard API mocks for all common endpoints.
 * Call this at the start of each test to avoid real backend calls.
 */
export async function mockAllApis(page: Page, overrides: MockOverrides = {}) {
  // Health
  await page.route('**/api/health', (route: Route) =>
    route.fulfill({ json: overrides.health ?? healthResponse })
  );

  // Config status
  await page.route('**/api/config/status', (route: Route) =>
    route.fulfill({ json: overrides.configStatus ?? configStatus })
  );

  // Config projects
  await page.route('**/api/config/projects', (route: Route) =>
    route.fulfill({
      json: {
        projects: configStatus.token_info.projects,
        bastion_login: configStatus.bastion_username,
        email: configStatus.token_info.email,
        name: configStatus.token_info.name,
      },
    })
  );

  // Slices
  await page.route('**/api/slices', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: overrides.slices ?? emptySliceList });
    }
    // POST create — handled per-test
    return route.fallback();
  });

  // Sites
  await page.route('**/api/sites', (route: Route) =>
    route.fulfill({ json: overrides.sites ?? sitesList })
  );

  // Component models
  await page.route('**/api/component-models', (route: Route) =>
    route.fulfill({ json: componentModels })
  );

  // Images
  await page.route('**/api/images', (route: Route) =>
    route.fulfill({ json: imageList })
  );

  // Templates
  await page.route('**/api/templates', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: overrides.templates ?? templatesList });
    }
    return route.fallback();
  });

  // VM Templates
  await page.route('**/api/vm-templates', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: overrides.vmTemplates ?? vmTemplatesList });
    }
    return route.fallback();
  });

  // Version
  await page.route('**/api/version', (route: Route) =>
    route.fulfill({ json: { version: '0.1.32-beta' } })
  );

  // Check update
  await page.route('**/api/check-update', (route: Route) =>
    route.fulfill({
      json: {
        current_version: '0.1.32-beta',
        latest_version: '0.1.32-beta',
        update_available: false,
        docker_hub_url: '',
        published_at: null,
      },
    })
  );

  // Jupyter
  await page.route('**/api/jupyter/**', (route: Route) =>
    route.fulfill({ json: {} })
  );

  // Config (general)
  await page.route('**/api/config', (route: Route) =>
    route.fulfill({ json: overrides.configStatus ?? configStatus })
  );

  // Config AI tools
  await page.route('**/api/config/ai-tools', (route: Route) =>
    route.fulfill({ json: {} })
  );

  // Config check-update
  await page.route('**/api/config/check-update', (route: Route) =>
    route.fulfill({
      json: {
        current_version: '0.1.32-beta',
        latest_version: '0.1.32-beta',
        update_available: false,
      },
    })
  );

  // Config keys
  await page.route('**/api/config/keys/**', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Config slice-key
  await page.route('**/api/config/slice-key/**', (route: Route) =>
    route.fulfill({ json: {} })
  );

  // Artifacts (list — matches /api/artifacts and /api/artifacts/my)
  await page.route('**/api/artifacts/**', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: [] });
    }
    return route.fallback();
  });

  await page.route('**/api/artifacts', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: [] });
    }
    return route.fallback();
  });

  // Recipes
  await page.route('**/api/recipes', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // AI tools status
  await page.route('**/api/ai/tools/status', (route: Route) =>
    route.fulfill({ json: {} })
  );

  // Template background runs
  await page.route('**/api/templates/runs', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Links (backbone links between sites)
  await page.route('**/api/links', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Facility ports
  await page.route('**/api/facility-ports', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Projects
  await page.route('**/api/projects', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        json: {
          projects: configStatus.token_info.projects,
          active_project_id: configStatus.project_id,
        },
      });
    }
    return route.fallback();
  });

  // Catch-all for unhandled API routes — return 404 instead of timing out
  await page.route('**/api/**', (route: Route) => {
    const method = route.request().method();
    const url = route.request().url();
    console.warn(`[mock] Unhandled API: ${method} ${url}`);
    return route.fallback();
  });
}
