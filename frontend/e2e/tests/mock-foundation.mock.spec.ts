import { expect, test } from '@playwright/test';
import { mockAllApis } from '../fixtures/api-mocks';
import {
  makeChameleonSlice,
  makeDefaultApiScenario,
  makeFederatedSlice,
  makeNode,
  makeSliceData,
} from '../fixtures/test-data';

test.describe('mocked API foundation', () => {
  test('loads the app with strict fixture-backed API mocks', async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/');

    await expect(page.getByRole('button', { name: /View FABRIC/ })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Slices', exact: true })).toBeVisible();
    await expect(page.getByRole('row', { name: /mock-fabric/ })).toBeVisible();
  });

  test('serves FABRIC, Chameleon, and Federated fixture builders', async ({ page }) => {
    const fabric = makeSliceData('fixture-fabric', 'fixture-fabric-id', {
      nodes: [makeNode('node1', 'RENC')],
    });
    const chameleon = makeChameleonSlice('fixture-chameleon', 'fixture-chameleon-id');
    const federated = makeFederatedSlice('fixture-federated', 'fixture-federated-id', {
      fabricSlices: [{ id: fabric.id, name: fabric.name, state: fabric.state, node_count: 1 }],
      chameleonSlices: [{ id: chameleon.id, name: chameleon.name, state: chameleon.state, site: chameleon.site }],
    });
    const scenario = makeDefaultApiScenario({
      slices: [fabric],
      chameleonSlices: [chameleon],
      federatedSlices: [federated],
    });
    await mockAllApis(page, scenario);
    await page.goto('/');

    const payload = await page.evaluate(async () => {
      const [fabricSlices, chameleonSlices, federatedSlices] = await Promise.all([
        fetch('/api/slices').then(r => r.json()),
        fetch('/api/chameleon/slices').then(r => r.json()),
        fetch('/api/federated/slices').then(r => r.json()),
      ]);
      return { fabricSlices, chameleonSlices, federatedSlices };
    });

    expect(payload.fabricSlices[0].name).toBe('fixture-fabric');
    expect(payload.chameleonSlices[0].name).toBe('fixture-chameleon');
    expect(payload.federatedSlices[0].name).toBe('fixture-federated');
  });
});
