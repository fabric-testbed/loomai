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
 *
 * Playwright routes are LIFO — last registered is checked first.
 * The catch-all is registered FIRST (checked last) as a safety net
 * for unhandled endpoints. Specific handlers are registered AFTER
 * and therefore take priority.
 */
export async function mockAllApis(page: Page, overrides: MockOverrides = {}) {
  // ── Catch-all (registered FIRST → checked LAST due to LIFO) ───
  // Falls through to real server for any un-mocked endpoints.
  // Tests using mocks should stay on pages that don't need complex data.
  await page.route('**/api/**', (route: Route) => {
    return route.fallback();
  });

  // ── Specific handlers (registered AFTER → checked BEFORE catch-all) ───

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

  // Slices — use URL function to match regardless of query params
  await page.route(
    (url: URL) => url.pathname === '/api/slices',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: overrides.slices ?? emptySliceList });
      }
      return route.fallback();
    }
  );

  // Sites — URL function to match regardless of query params
  await page.route(
    (url: URL) => url.pathname === '/api/sites',
    (route: Route) => route.fulfill({ json: overrides.sites ?? sitesList })
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
  await page.route(
    (url: URL) => url.pathname === '/api/templates',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: overrides.templates ?? templatesList });
      }
      return route.fallback();
    }
  );

  // VM Templates
  await page.route(
    (url: URL) => url.pathname === '/api/vm-templates',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: overrides.vmTemplates ?? vmTemplatesList });
      }
      return route.fallback();
    }
  );

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

  // Jupyter (sub-paths)
  await page.route('**/api/jupyter/**', (route: Route) =>
    route.fulfill({ json: {} })
  );

  // Config (general — exact match to avoid catching /api/config/*)
  await page.route(
    (url: URL) => url.pathname === '/api/config',
    (route: Route) => route.fulfill({ json: overrides.configStatus ?? configStatus })
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

  // Artifacts (sub-paths)
  await page.route('**/api/artifacts/**', (route: Route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: [] });
    }
    return route.fulfill({ json: {}, status: 200 });
  });

  // Artifacts (exact)
  await page.route(
    (url: URL) => url.pathname === '/api/artifacts',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: {}, status: 200 });
    }
  );

  // Recipes
  await page.route('**/api/recipes', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Views status
  await page.route('**/api/views/status', (route: Route) =>
    route.fulfill({ json: { fabric_enabled: true, chameleon_enabled: false, composite_enabled: true } })
  );

  // Chameleon status
  await page.route('**/api/chameleon/status', (route: Route) =>
    route.fulfill({ json: { enabled: false, configured: false, sites: {} } })
  );

  // Chameleon slices
  await page.route(
    (url: URL) => url.pathname === '/api/chameleon/slices',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: {}, status: 200 });
    }
  );

  // Chameleon leases
  await page.route('**/api/chameleon/leases', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Chameleon instances
  await page.route('**/api/chameleon/instances', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Composite slices
  await page.route(
    (url: URL) => url.pathname === '/api/composite/slices',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({ json: [] });
      }
      return route.fulfill({ json: {}, status: 200 });
    }
  );

  // AI tools status
  await page.route('**/api/ai/tools/status', (route: Route) =>
    route.fulfill({ json: {} })
  );

  // Template background runs
  await page.route('**/api/templates/runs', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Links
  await page.route('**/api/links', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Facility ports
  await page.route('**/api/facility-ports', (route: Route) =>
    route.fulfill({ json: [] })
  );

  // Projects
  await page.route(
    (url: URL) => url.pathname === '/api/projects',
    (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          json: {
            projects: configStatus.token_info.projects,
            active_project_id: configStatus.project_id,
          },
        });
      }
      return route.fulfill({ json: {}, status: 200 });
    }
  );
}
