import { expect, test, type APIResponse } from '@playwright/test';

const backendBaseUrl = process.env.E2E_BACKEND_URL
  ?? `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || '8010'}`;

async function expectOk(response: APIResponse): Promise<APIResponse> {
  if (!response.ok()) {
    expect(response.ok(), `${response.url()} returned ${response.status()}: ${await response.text()}`).toBe(true);
  }
  expect(response.ok()).toBe(true);
  return response;
}

async function expectStatus(response: APIResponse, status: number): Promise<APIResponse> {
  expect(response.status(), `${response.url()} returned ${response.status()}: ${await response.text()}`).toBe(status);
  return response;
}

test.describe('backend contract', () => {
  test.beforeEach(async ({ request }) => {
    await expectOk(await request.post(`${backendBaseUrl}/api/__test/reset`));
  });

  test('serves core status APIs from a real contract-mode backend', async ({ request }) => {
    const responses = await Promise.all([
      request.get(`${backendBaseUrl}/api/health`),
      request.get(`${backendBaseUrl}/api/config`),
      request.get(`${backendBaseUrl}/api/views/status`),
      request.get(`${backendBaseUrl}/api/chameleon/status`),
    ]);

    for (const response of responses) {
      expect(response.ok(), `${response.url()} returned ${response.status()}`).toBe(true);
    }

    const [health, config, views, chameleon] = await Promise.all(responses.map(response => response.json()));
    expect(health.status).toBe('ok');
    expect(config).toHaveProperty('configured');
    expect(views.fabric_enabled).toBe(true);
    expect(chameleon.enabled).toBe(true);
    expect(chameleon.configured).toBe(true);
    expect(chameleon.sites['CHI@TACC'].configured).toBe(true);
  });

  test('covers the FABRIC slice lifecycle without live FABRIC calls', async ({ request }) => {
    const sliceName = 'contract-fabric-lifecycle';

    const created = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices?name=${encodeURIComponent(sliceName)}`),
    )).json();
    expect(created.name).toBe(sliceName);
    expect(created.state).toBe('Draft');

    await expectOk(await request.post(`${backendBaseUrl}/api/slices/${sliceName}/nodes`, {
      data: {
        name: 'fabric-node-1',
        site: 'RENC',
        cores: 2,
        ram: 8,
        disk: 10,
        image: 'default_ubuntu_22',
      },
    }));

    const withComponent = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/nodes/fabric-node-1/components`, {
        data: { name: 'nic1', model: 'NIC_Basic' },
      }),
    )).json();
    const interfaceName = withComponent.nodes[0].components[0].interfaces[0].name;
    expect(interfaceName).toBe('fabric-node-1-nic1-p1');

    const withNetwork = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/networks`, {
        data: {
          name: 'fabric-net-1',
          type: 'L2Bridge',
          interfaces: [interfaceName],
          subnet: '192.168.10.0/24',
          gateway: '192.168.10.1',
        },
      }),
    )).json();
    expect(withNetwork.networks).toHaveLength(1);
    expect(withNetwork.graph.nodes.length).toBeGreaterThan(0);
    expect(withNetwork.graph.edges.length).toBeGreaterThan(0);

    const submitted = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/submit`),
    )).json();
    expect(submitted.id).toBe('contract-fabric-lifecycle');
    expect(submitted.state).toBe('StableOK');

    const listed = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/slices?max_age=0`),
    )).json();
    expect(listed.some((slice: { name: string; state: string }) => (
      slice.name === sliceName && slice.state === 'StableOK'
    ))).toBe(true);
  });

  test('covers FABRIC facility port and port mirror operations', async ({ request }) => {
    const sliceName = 'contract-fabric-cross-services';

    await expectOk(await request.post(`${backendBaseUrl}/api/slices?name=${encodeURIComponent(sliceName)}`));
    await expectOk(await request.post(`${backendBaseUrl}/api/slices/${sliceName}/nodes`, {
      data: {
        name: 'fabric-node-1',
        site: 'RENC',
        cores: 2,
        ram: 8,
        disk: 10,
        image: 'default_ubuntu_22',
      },
    }));

    const withSourceNic = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/nodes/fabric-node-1/components`, {
        data: { name: 'source-nic', model: 'NIC_Basic' },
      }),
    )).json();
    const sourceInterface = withSourceNic.nodes[0].components[0].interfaces[0].name;
    expect(sourceInterface).toBe('fabric-node-1-source-nic-p1');

    const withCaptureNic = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/nodes/fabric-node-1/components`, {
        data: { name: 'capture-nic', model: 'NIC_Basic' },
      }),
    )).json();
    const captureInterface = withCaptureNic.nodes[0].components
      .find((component: { name: string }) => component.name === 'capture-nic')
      .interfaces[0].name;
    expect(captureInterface).toBe('fabric-node-1-capture-nic-p1');

    const withFacilityPort = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/facility-ports`, {
        data: {
          name: 'contract-fp',
          site: 'RENC',
          vlan: '3101',
          bandwidth: 10,
        },
      }),
    )).json();
    expect(withFacilityPort.facility_ports).toHaveLength(1);
    expect(withFacilityPort.facility_ports[0]).toMatchObject({
      name: 'contract-fp',
      site: 'RENC',
      vlan: '3101',
    });
    expect(withFacilityPort.graph.nodes.some((node: { data: { element_type?: string; name?: string } }) => (
      node.data.element_type === 'facility-port' && node.data.name === 'contract-fp'
    ))).toBe(true);
    const facilityPortInterface = withFacilityPort.facility_ports[0].interfaces[0].name;
    expect(facilityPortInterface).toBe('contract-fp-p1');

    const updatedFacilityPort = await (await expectOk(
      await request.put(`${backendBaseUrl}/api/slices/${sliceName}/facility-ports/contract-fp`, {
        data: {
          vlan: '3102',
          bandwidth: 20,
        },
      }),
    )).json();
    expect(updatedFacilityPort.facility_ports[0]).toMatchObject({
      name: 'contract-fp',
      vlan: '3102',
      bandwidth: '20',
    });

    const withFpNetwork = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/networks`, {
        data: {
          name: 'facility-l2',
          type: 'L2Bridge',
          interfaces: [sourceInterface, facilityPortInterface],
          vlan: '3102',
        },
      }),
    )).json();
    const fpNetwork = withFpNetwork.networks.find((network: { name: string }) => network.name === 'facility-l2');
    expect(fpNetwork.interfaces.map((iface: { name: string }) => iface.name).sort()).toEqual([
      facilityPortInterface,
      sourceInterface,
    ].sort());

    const withPortMirror = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/slices/${sliceName}/port-mirrors`, {
        data: {
          name: 'contract-mirror',
          mirror_interface_name: sourceInterface,
          receive_interface_name: captureInterface,
          mirror_direction: 'both',
        },
      }),
    )).json();
    expect(withPortMirror.port_mirrors).toHaveLength(1);
    expect(withPortMirror.port_mirrors[0]).toMatchObject({
      name: 'contract-mirror',
      mirror_interface_name: sourceInterface,
      receive_interface_name: captureInterface,
      mirror_direction: 'both',
    });
    expect(JSON.stringify(withPortMirror.graph)).toContain('contract-fp');
    expect(JSON.stringify(withPortMirror.graph)).toContain('contract-mirror');

    const withoutMirror = await (await expectOk(
      await request.delete(`${backendBaseUrl}/api/slices/${sliceName}/port-mirrors/contract-mirror`),
    )).json();
    expect(withoutMirror.port_mirrors).toHaveLength(0);

    const withoutFacilityPort = await (await expectOk(
      await request.delete(`${backendBaseUrl}/api/slices/${sliceName}/facility-ports/contract-fp`),
    )).json();
    expect(withoutFacilityPort.facility_ports).toHaveLength(0);
  });

  test('covers the Chameleon draft lifecycle without live OpenStack calls', async ({ request }) => {
    const draft = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/chameleon/drafts`, {
        data: { name: 'contract-chi', site: 'CHI@TACC' },
      }),
    )).json();
    expect(draft.state).toBe('Draft');

    const withNode = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/chameleon/drafts/${draft.id}/nodes`, {
        data: {
          name: 'chi-node-1',
          node_type: 'compute_haswell',
          image: 'CC-Ubuntu22.04',
          count: 1,
          site: 'CHI@TACC',
        },
      }),
    )).json();
    const nodeId = withNode.nodes[0].id;
    expect(withNode.nodes[0].site).toBe('CHI@TACC');

    await expectOk(await request.post(`${backendBaseUrl}/api/chameleon/drafts/${draft.id}/networks`, {
      data: { name: 'chi-net-1', connected_nodes: [nodeId] },
    }));
    await expectOk(await request.put(`${backendBaseUrl}/api/chameleon/drafts/${draft.id}/floating-ips`, {
      data: { entries: [{ node_id: nodeId, nic: 0 }] },
    }));

    await expectOk(await request.post(`${backendBaseUrl}/api/chameleon/slices/${draft.id}/import-reservation`, {
      data: {
        site: 'CHI@TACC',
        lease_id: 'contract-lease-1',
        include_lease: true,
      },
    }));

    const allSlices = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/slices/all`),
    )).json();
    const current = allSlices.find((slice: { id: string }) => slice.id === draft.id);
    expect(current).toBeTruthy();
    expect(current.resources.some((resource: { type: string; id: string }) => (
      resource.type === 'lease' && resource.id === 'contract-lease-1'
    ))).toBe(true);

    const graph = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/drafts/${draft.id}/graph`),
    )).json();
    expect(graph.nodes.length).toBeGreaterThan(0);
    expect(JSON.stringify(graph)).toContain('chi-node-1');
  });

  test('covers Chameleon floating IP and security group operations', async ({ request }) => {
    const initialFloatingIps = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/floating-ips?site=CHI@TACC`),
    )).json();
    expect(initialFloatingIps).toHaveLength(0);

    const allocatedIp = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/chameleon/floating-ips`, {
        data: {
          site: 'CHI@TACC',
          network: 'public',
        },
      }),
    )).json();
    expect(allocatedIp).toMatchObject({
      id: 'contract-fip-1',
      floating_ip_address: '198.51.100.10',
      _site: 'CHI@TACC',
    });

    const associatedIp = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/chameleon/floating-ips/${allocatedIp.id}/associate`, {
        data: {
          site: 'CHI@TACC',
          port_id: 'contract-port-1',
        },
      }),
    )).json();
    expect(associatedIp.port_id).toBe('contract-port-1');
    expect(associatedIp.status).toBe('ACTIVE');

    const afterAllocation = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/floating-ips?site=CHI@TACC`),
    )).json();
    expect(afterAllocation).toHaveLength(1);
    expect(afterAllocation[0].id).toBe(allocatedIp.id);

    await expectOk(await request.delete(`${backendBaseUrl}/api/chameleon/floating-ips/${allocatedIp.id}?site=CHI@TACC`));
    const afterRelease = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/floating-ips?site=CHI@TACC`),
    )).json();
    expect(afterRelease).toHaveLength(0);

    const defaultSecurityGroups = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/security-groups?site=CHI@TACC`),
    )).json();
    expect(defaultSecurityGroups.map((group: { name: string }) => group.name)).toContain('default');

    const securityGroup = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/chameleon/security-groups`, {
        data: {
          site: 'CHI@TACC',
          name: 'contract-sg',
          description: 'Contract security group',
        },
      }),
    )).json();
    expect(securityGroup).toMatchObject({
      id: 'contract-sg-2',
      name: 'contract-sg',
      _site: 'CHI@TACC',
    });

    const rule = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/chameleon/security-groups/${securityGroup.id}/rules`, {
        data: {
          site: 'CHI@TACC',
          direction: 'ingress',
          protocol: 'tcp',
          port_range_min: 22,
          port_range_max: 22,
          remote_ip_prefix: '0.0.0.0/0',
          ethertype: 'IPv4',
        },
      }),
    )).json();
    expect(rule).toMatchObject({
      id: 'contract-sg-rule-1',
      security_group_id: securityGroup.id,
      protocol: 'tcp',
      port_range_min: 22,
    });

    const withRule = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/security-groups?site=CHI@TACC`),
    )).json();
    const currentSecurityGroup = withRule.find((group: { id: string }) => group.id === securityGroup.id);
    expect(currentSecurityGroup.security_group_rules).toHaveLength(1);

    await expectOk(
      await request.delete(`${backendBaseUrl}/api/chameleon/security-groups/${securityGroup.id}/rules/${rule.id}?site=CHI@TACC`),
    );
    const withoutRule = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/security-groups?site=CHI@TACC`),
    )).json();
    expect(withoutRule.find((group: { id: string }) => group.id === securityGroup.id).security_group_rules).toHaveLength(0);

    await expectOk(await request.delete(`${backendBaseUrl}/api/chameleon/security-groups/${securityGroup.id}?site=CHI@TACC`));
    const afterSecurityGroupDelete = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/chameleon/security-groups?site=CHI@TACC`),
    )).json();
    expect(afterSecurityGroupDelete.map((group: { id: string }) => group.id)).not.toContain(securityGroup.id);
  });

  test('covers federated member and connection APIs with seeded provider slices', async ({ request }) => {
    const seed = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/__test/seed`, {
        data: { scenario: 'federated-one-of-each' },
      }),
    )).json();
    expect(seed.fabric.slice_id).toBe('contract-fabric-slice');
    expect(seed.chameleon.slice_id).toBe('chi-contract-slice');

    const federated = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/federated/slices`, {
        data: { name: 'contract-fed' },
      }),
    )).json();
    expect(federated.kind).toBe('federated');

    await expectOk(await request.post(`${backendBaseUrl}/api/federated/slices/${federated.id}/members/add`, {
      data: {
        provider: 'fabric',
        slice_id: seed.fabric.slice_id,
        name: seed.fabric.name,
      },
    }));
    await expectOk(await request.post(`${backendBaseUrl}/api/federated/slices/${federated.id}/members/add`, {
      data: {
        provider: 'chameleon',
        slice_id: seed.chameleon.slice_id,
        name: seed.chameleon.name,
      },
    }));

    const withMembers = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/federated/slices/${federated.id}`),
    )).json();
    expect(withMembers.members.map((member: { provider: string }) => member.provider).sort()).toEqual([
      'chameleon',
      'fabric',
    ]);
    expect(withMembers.fabric_slices).toEqual([seed.fabric.slice_id]);
    expect(withMembers.chameleon_slices).toEqual([seed.chameleon.slice_id]);

    await expectOk(await request.post(`${backendBaseUrl}/api/federated/slices/${federated.id}/connections/add`, {
      data: {
        id: 'conn-contract-fabnetv4',
        type: 'fabnetv4',
        endpoint_a: {
          provider: 'fabric',
          slice_id: seed.fabric.slice_id,
          node: seed.fabric.node,
        },
        endpoint_b: {
          provider: 'chameleon',
          slice_id: seed.chameleon.slice_id,
          node: seed.chameleon.node,
        },
      },
    }));

    const connections = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/federated/slices/${federated.id}/connections`),
    )).json();
    expect(connections).toHaveLength(1);
    expect(connections[0].id).toBe('conn-contract-fabnetv4');
    expect(connections[0].endpoint_a.slice_id).toBe(seed.fabric.slice_id);
    expect(connections[0].endpoint_b.slice_id).toBe(seed.chameleon.slice_id);

    const graph = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/federated/slices/${federated.id}/graph`),
    )).json();
    const graphText = JSON.stringify(graph);
    expect(graphText).toContain('contract-fabric-slice');
    expect(graphText).toContain('chi-contract-slice');
    expect(graphText).toContain('conn-contract-fabnetv4');
  });

  test('covers federated Facility Port L2 connection plans with seeded provider slices', async ({ request }) => {
    const seed = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/__test/seed`, {
        data: { scenario: 'federated-one-of-each' },
      }),
    )).json();

    const federated = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/federated/slices`, {
        data: { name: 'contract-fed-fp-l2' },
      }),
    )).json();

    await expectOk(await request.post(`${backendBaseUrl}/api/federated/slices/${federated.id}/members/add`, {
      data: {
        provider: 'fabric',
        slice_id: seed.fabric.slice_id,
        name: seed.fabric.name,
      },
    }));
    await expectOk(await request.post(`${backendBaseUrl}/api/federated/slices/${federated.id}/members/add`, {
      data: {
        provider: 'chameleon',
        slice_id: seed.chameleon.slice_id,
        name: seed.chameleon.name,
      },
    }));

    await expectOk(await request.post(`${backendBaseUrl}/api/federated/slices/${federated.id}/connections/add`, {
      data: {
        id: 'conn-contract-fp-l2',
        type: 'facility_port_l2',
        facility_port: 'contract-fp',
        vlan: '3101',
        fabric_site: 'RENC',
        chameleon_site: 'CHI@TACC',
        endpoint_a: {
          provider: 'fabric',
          slice_id: seed.fabric.slice_id,
          node: seed.fabric.node,
          network: 'fp-l2-net',
          facility_port: 'contract-fp',
          vlan: '3101',
          site: 'RENC',
        },
        endpoint_b: {
          provider: 'chameleon',
          slice_id: seed.chameleon.slice_id,
          node: seed.chameleon.node,
          network: 'chi-vlan-3101',
          vlan: '3101',
          site: 'CHI@TACC',
        },
      },
    }));

    const plan = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/federated/slices/${federated.id}/connection-plan`),
    )).json();
    expect(plan).toHaveLength(1);
    expect(plan[0]).toMatchObject({
      id: 'conn-contract-fp-l2',
      type: 'facility_port_l2',
      status: 'ready-for-submit',
      vlan: '3101',
      facility_port: 'contract-fp',
      fabric_slice: seed.fabric.slice_id,
      chameleon_slice: seed.chameleon.slice_id,
      fabric_site: 'RENC',
      chameleon_site: 'CHI@TACC',
    });
    expect(plan[0].actions).toEqual(expect.arrayContaining([
      expect.stringContaining('Chameleon VLAN network'),
      expect.stringContaining('FABRIC facility port'),
    ]));

    const graph = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/federated/slices/${federated.id}/graph`),
    )).json();
    const graphText = JSON.stringify(graph);
    expect(graphText).toContain('conn-contract-fp-l2');
    expect(graphText).toContain('Facility Port L2');
    expect(graphText).toContain('VLAN 3101');
  });

  test('covers settings read/update and deterministic validation endpoints', async ({ request }) => {
    const settings = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/settings`),
    )).json();
    expect(settings.paths.storage_dir).toBeTruthy();
    expect(settings.fabric.hosts.bastion).toBeTruthy();

    const updated = {
      ...settings,
      views: { ...(settings.views || {}), composite_enabled: false },
      services: { ...settings.services, jupyter_port: 8899 },
    };
    const saved = await (await expectOk(
      await request.put(`${backendBaseUrl}/api/settings`, { data: updated }),
    )).json();
    expect(saved.views.composite_enabled).toBe(false);
    expect(saved.services.jupyter_port).toBe(8899);

    const tokenCheck = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/settings/test/token`),
    )).json();
    expect(tokenCheck).toHaveProperty('ok');
    expect(tokenCheck).toHaveProperty('message');

    const customProviderCheck = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/settings/test-custom-provider`, {
        data: { base_url: 'http://127.0.0.1:9', api_key: 'contract-key' },
      }),
    )).json();
    expect(customProviderCheck).toHaveProperty('ok');
    expect(customProviderCheck).toHaveProperty('message');
  });

  test('covers container file CRUD used by the file-transfer UI', async ({ request }) => {
    await expectOk(await request.put(`${backendBaseUrl}/api/files/content`, {
      data: { path: 'contract-note.txt', content: 'contract file contents' },
    }));

    const content = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/files/content?path=contract-note.txt`),
    )).json();
    expect(content).toEqual({ path: 'contract-note.txt', content: 'contract file contents' });

    const rootList = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/files`),
    )).json();
    expect(rootList.some((entry: { name: string; type: string }) => (
      entry.name === 'contract-note.txt' && entry.type === 'file'
    ))).toBe(true);

    const folder = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/files/mkdir`, {
        data: { name: 'contract-folder' },
      }),
    )).json();
    expect(folder.created).toBe('contract-folder');

    await expectOk(await request.delete(`${backendBaseUrl}/api/files?path=contract-note.txt`));
    await expectOk(await request.delete(`${backendBaseUrl}/api/files?path=contract-folder`));
  });

  test('covers local and remote artifact APIs without Artifact Manager access', async ({ request }) => {
    const created = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/templates/create-blank`, {
        data: {
          name: 'Contract Harness Artifact',
          description: 'Created by backend contract tests',
          category: 'weave',
        },
      }),
    )).json();
    expect(created.dir_name).toBe('Contract_Harness_Artifact');

    const local = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/artifacts/local`),
    )).json();
    expect(local.artifacts.some((artifact: { dir_name: string; category: string }) => (
      artifact.dir_name === 'Contract_Harness_Artifact' && artifact.category === 'weave'
    ))).toBe(true);

    const mine = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/artifacts/my`),
    )).json();
    expect(mine.local_artifacts.some((artifact: { dir_name: string }) => artifact.dir_name === 'Contract_Harness_Artifact')).toBe(true);
    expect(mine.authored_remote_only).toEqual(expect.any(Array));

    const remote = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/artifacts/remote`),
    )).json();
    expect(remote.artifacts[0]).toMatchObject({
      uuid: 'contract-remote-artifact',
      category: 'weave',
    });
    expect(remote.tags.map((tag: { name: string }) => tag.name)).toContain('mock');

    const tags = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/artifacts/valid-tags`),
    )).json();
    expect(tags.tags.map((tag: { tag: string }) => tag.tag)).toContain('weave');
  });

  test('covers deterministic AI model status and default model APIs', async ({ request }) => {
    const models = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/ai/models`),
    )).json();
    expect(models.fabric[0]).toMatchObject({
      id: 'fabric/contract-model',
      healthy: true,
      supports_tools: true,
    });
    expect(models.has_key.fabric).toBe(true);

    const updatedDefault = await (await expectOk(
      await request.put(`${backendBaseUrl}/api/ai/models/default`, {
        data: { model: 'fabric/contract-model', source: 'fabric' },
      }),
    )).json();
    expect(updatedDefault).toEqual({ default: 'fabric/contract-model', source: 'fabric' });

    const defaultModel = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/ai/models/default`),
    )).json();
    expect(defaultModel.default).toBe('fabric/contract-model');

    const refreshed = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/ai/models/refresh`),
    )).json();
    expect(refreshed.message).toEqual(expect.any(String));
    expect(refreshed.fabric[0].id).toBe('fabric/contract-model');

    const rag = await (await expectOk(
      await request.get(`${backendBaseUrl}/api/ai/rag/status`),
    )).json();
    expect(rag).toHaveProperty('status');
    expect(rag).toHaveProperty('chunk_count');
  });

  test('covers deterministic error paths for shared file/settings/AI contracts', async ({ request }) => {
    const missingFile = await (await expectStatus(
      await request.get(`${backendBaseUrl}/api/files/content?path=missing-contract-file.txt`),
      404,
    )).json();
    expect(missingFile.detail).toBe('File not found');

    const traversal = await (await expectStatus(
      await request.get(`${backendBaseUrl}/api/files?path=../../etc`),
      400,
    )).json();
    expect(traversal.detail).toContain('Path traversal');

    const missingProviderBase = await (await expectOk(
      await request.post(`${backendBaseUrl}/api/settings/test-custom-provider`, {
        data: { base_url: '', api_key: 'contract-key' },
      }),
    )).json();
    expect(missingProviderBase).toMatchObject({
      ok: false,
      message: 'No base URL provided',
    });

    const missingDefaultModel = await (await expectStatus(
      await request.put(`${backendBaseUrl}/api/ai/models/default`, {
        data: { source: 'fabric' },
      }),
      400,
    )).json();
    expect(missingDefaultModel.error).toBe('model is required');

    const missingHealthModel = await (await expectStatus(
      await request.post(`${backendBaseUrl}/api/ai/models/test`, {
        data: { source: 'fabric' },
      }),
      400,
    )).json();
    expect(missingHealthModel.error).toBe('model is required');
  });
});
