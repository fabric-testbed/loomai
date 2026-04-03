/** API client for the LoomAI backend. */

import type { SliceSummary, SliceData, SiteInfo, SiteDetail, LinkInfo, ComponentModel, ConfigStatus, ProjectsResponse, ValidationResult, SiteMetrics, LinkMetrics, FileEntry, ProvisionRule, BootConfig, BootExecResult, SliceKeySet, VMTemplateSummary, VMTemplateDetail, VMTemplateVariantDetail, HostInfo, ProjectDetails, ToolFile, RecipeSummary, RecipeExecResult, UpdateInfo, IpHint, L3Config, FacilityPortInfo, LoomAISettings, ToolConfigStatus, UsersResponse, CalendarData, NextAvailableResult, AlternativeResult, ExperimentVariable } from '../types/fabric';

const BASE = '/api';

// In-flight GET request deduplication — if the same GET URL is already
// pending, return the existing promise instead of firing a duplicate request.
const _inflight = new Map<string, Promise<any>>();

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const method = (options?.method || 'GET').toUpperCase();

  // Only deduplicate GET requests (mutations must always fire)
  if (method === 'GET') {
    const existing = _inflight.get(url);
    if (existing) return existing as Promise<T>;
    const promise = _doFetch<T>(url, options).finally(() => _inflight.delete(url));
    _inflight.set(url, promise);
    return promise;
  }
  return _doFetch<T>(url, options);
}

async function _doFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

// --- Slices ---

export function listSlices(maxAge?: number): Promise<SliceSummary[]> {
  const params = maxAge !== undefined ? `?max_age=${maxAge}` : '';
  return fetchJson(`/slices${params}`);
}

export function getSlice(name: string): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(name)}`);
}

export function createSlice(name: string): Promise<SliceData> {
  return fetchJson(`/slices?name=${encodeURIComponent(name)}`, { method: 'POST' });
}

export function submitSlice(name: string): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/submit`, { method: 'POST' });
}

export function refreshSlice(name: string): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/refresh`, { method: 'POST' });
}

export function getSliceState(name: string): Promise<{name: string; id: string; state: string; has_errors: boolean}> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/state`);
}

export interface SliverStateEntry {
  name: string;
  reservation_state: string;
  site: string;
  management_ip: string;
  state_color: string;
  error_message: string;
}
export interface SliverStatesResponse {
  slice_name: string;
  slice_state: string;
  nodes: SliverStateEntry[];
}
export function getSliverStates(nameOrId: string, maxAge: number = 15): Promise<SliverStatesResponse> {
  return fetchJson(`/slices/${encodeURIComponent(nameOrId)}/slivers?max_age=${maxAge}`);
}

export function validateSlice(name: string): Promise<ValidationResult> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/validate`);
}

export function deleteSlice(name: string): Promise<{ status: string }> {
  return fetchJson(`/slices/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function archiveSlice(name: string): Promise<{ status: string; name: string }> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/archive`, { method: 'POST' });
}

export function archiveAllTerminal(): Promise<{ archived: string[]; count: number }> {
  return fetchJson('/slices/archive-terminal', { method: 'POST' });
}

export function reconcileProjects(): Promise<{ tagged: number; projects_scanned: number; slices_found: number }> {
  return fetchJson('/slices/reconcile-projects', { method: 'POST' });
}

export function renewLease(name: string, endDate: string): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/renew`, {
    method: 'POST',
    body: JSON.stringify({ end_date: endDate }),
  });
}

export function cloneSlice(name: string, newName: string): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/clone?new_name=${encodeURIComponent(newName)}`, { method: 'POST' });
}

// --- Nodes ---

export function addNode(
  sliceName: string,
  node: {
    name: string; site?: string; cores?: number; ram?: number; disk?: number; image?: string;
    host?: string; image_type?: string; username?: string; instance_type?: string;
    components?: Array<{ name: string; model: string }>;
  }
): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/nodes`, {
    method: 'POST',
    body: JSON.stringify(node),
  });
}

export function removeNode(sliceName: string, nodeName: string): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/nodes/${encodeURIComponent(nodeName)}`,
    { method: 'DELETE' }
  );
}

export function updateNode(
  sliceName: string,
  nodeName: string,
  updates: { site?: string; host?: string; cores?: number; ram?: number; disk?: number; image?: string }
): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/nodes/${encodeURIComponent(nodeName)}`,
    { method: 'PUT', body: JSON.stringify(updates) }
  );
}

// --- Components ---

export function addComponent(
  sliceName: string,
  nodeName: string,
  comp: { name: string; model: string }
): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/nodes/${encodeURIComponent(nodeName)}/components`,
    { method: 'POST', body: JSON.stringify(comp) }
  );
}

export function removeComponent(
  sliceName: string,
  nodeName: string,
  compName: string
): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/nodes/${encodeURIComponent(nodeName)}/components/${encodeURIComponent(compName)}`,
    { method: 'DELETE' }
  );
}

// --- Facility Ports ---

export function addFacilityPort(
  sliceName: string,
  data: { name: string; site: string; vlan?: string; bandwidth?: number }
): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/facility-ports`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function removeFacilityPort(sliceName: string, fpName: string): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/facility-ports/${encodeURIComponent(fpName)}`,
    { method: 'DELETE' }
  );
}

// --- Port Mirrors ---

export function addPortMirror(
  sliceName: string,
  data: { name: string; mirror_interface_name: string; receive_interface_name: string; mirror_direction?: string }
): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/port-mirrors`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function removePortMirror(sliceName: string, pmName: string): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/port-mirrors/${encodeURIComponent(pmName)}`,
    { method: 'DELETE' }
  );
}

// --- Networks ---

export function addNetwork(
  sliceName: string,
  net: {
    name: string;
    type?: string;
    interfaces?: string[];
    subnet?: string;
    gateway?: string;
    ip_mode?: string;
    interface_ips?: Record<string, string>;
  }
): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/networks`, {
    method: 'POST',
    body: JSON.stringify(net),
  });
}

export function updateNetwork(
  sliceName: string,
  netName: string,
  update: {
    subnet?: string;
    gateway?: string;
    ip_mode?: string;
    interface_ips?: Record<string, string>;
  }
): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}`,
    { method: 'PUT', body: JSON.stringify(update) }
  );
}

export function removeNetwork(sliceName: string, netName: string): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}`,
    { method: 'DELETE' }
  );
}

// --- IP Hints (L3 networks) ---

export function getIpHints(sliceName: string, netName: string): Promise<{ network: string; hints: Record<string, IpHint> }> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}/ip-hints`);
}

export function setIpHints(sliceName: string, netName: string, hints: Record<string, IpHint>): Promise<{ network: string; hints: Record<string, IpHint>; status: string }> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}/ip-hints`, {
    method: 'PUT',
    body: JSON.stringify({ hints }),
  });
}

export function applyIpHints(sliceName: string, netName: string): Promise<{ network: string; assignments: Record<string, string>; status: string }> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}/apply-ip-hints`, {
    method: 'POST',
  });
}

// --- L3 Config ---

export function getL3Config(sliceName: string, netName: string): Promise<{ network: string; l3_config: L3Config }> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}/l3-config`);
}

export function setL3Config(sliceName: string, netName: string, config: L3Config): Promise<{ network: string; l3_config: L3Config; status: string }> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/networks/${encodeURIComponent(netName)}/l3-config`, {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

// --- Post-boot config ---

export function setPostBootConfig(
  sliceName: string,
  nodeName: string,
  script: string
): Promise<SliceData> {
  return fetchJson(
    `/slices/${encodeURIComponent(sliceName)}/nodes/${encodeURIComponent(nodeName)}/post-boot`,
    { method: 'PUT', body: JSON.stringify({ script }) }
  );
}

// --- FABlib post_boot_config ---

export function runPostBootConfig(sliceName: string): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/post-boot-config`, { method: 'POST' });
}

export function autoConfigureNetworks(sliceName: string): Promise<{ configured: number; nodes: Record<string, number>; details: Record<string, any[]> }> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/auto-configure-networks`, { method: 'POST' });
}

// --- Slice export/import ---

export async function exportSlice(name: string): Promise<void> {
  const res = await fetch(`${BASE}/slices/${encodeURIComponent(name)}/export`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${name}.fabric.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function exportSliceJson(name: string): Promise<SliceModel> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/export`);
}

export function saveToStorage(name: string): Promise<{ status: string; path: string }> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/save-to-storage`, { method: 'POST' });
}

export function listStorageFiles(): Promise<Array<{ name: string; size: number; modified: number }>> {
  return fetchJson('/slices/storage-files');
}

export function openFromStorage(filename: string): Promise<SliceData> {
  return fetchJson('/slices/open-from-storage', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  });
}

export interface SliceModel {
  format: string;
  name: string;
  nodes: Array<{
    name: string;
    site: string;
    cores: number;
    ram: number;
    disk: number;
    image: string;
    post_boot_script?: string;
    components: Array<{ name: string; model: string }>;
  }>;
  networks: Array<{
    name: string;
    type: string;
    interfaces: string[];
    subnet?: string;
    gateway?: string;
    ip_mode?: string;
    interface_ips?: Record<string, string>;
    ip_hints?: Record<string, IpHint>;
  }>;
}

export function importSlice(model: SliceModel): Promise<SliceData> {
  return fetchJson('/slices/import', {
    method: 'POST',
    body: JSON.stringify(model),
  });
}

// --- Templates ---

export interface ScriptArg {
  name: string;
  label: string;
  type: 'string' | 'number' | 'boolean';
  required: boolean;
  default: string;
  description?: string;
  placeholder?: string;
}

export interface ScriptManifest {
  description?: string;
  args: ScriptArg[];
}

export interface TemplateSummary {
  name: string;
  description: string;
  description_short?: string;
  source_slice: string;
  created: string;
  dir_name: string;
  has_template?: boolean;
  has_cleanup_script?: boolean;
  is_experiment?: boolean;
  weave_config?: { run_script: string; log_file: string; args?: ScriptArg[]; cleanup_script?: string };
}

export function listTemplates(): Promise<TemplateSummary[]> {
  return fetchJson('/templates');
}

export function saveTemplate(data: { name: string; description: string; slice_name: string }): Promise<TemplateSummary> {
  return fetchJson('/templates', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function createBlankArtifact(data: { name: string; description?: string; category?: string }): Promise<{ dir_name: string }> {
  return fetchJson('/templates/create-blank', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function loadTemplate(name: string, sliceName?: string): Promise<SliceData> {
  return fetchJson(`/templates/${encodeURIComponent(name)}/load`, {
    method: 'POST',
    body: JSON.stringify({ slice_name: sliceName || '' }),
  });
}

export function deleteTemplate(name: string): Promise<{ status: string; name: string }> {
  return fetchJson(`/templates/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function updateTemplate(name: string, data: { description: string }): Promise<TemplateSummary> {
  return fetchJson(`/templates/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function getTemplate(name: string): Promise<TemplateSummary & { model: any; tools: ToolFile[] }> {
  return fetchJson(`/templates/${encodeURIComponent(name)}`);
}

export function readTemplateTool(templateName: string, filename: string): Promise<{ filename: string; content: string }> {
  return fetchJson(`/templates/${encodeURIComponent(templateName)}/tools/${encodeURIComponent(filename)}`);
}

export function writeTemplateTool(templateName: string, filename: string, content: string): Promise<{ filename: string; status: string }> {
  return fetchJson(`/templates/${encodeURIComponent(templateName)}/tools/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export function deleteTemplateTool(templateName: string, filename: string): Promise<{ filename: string; status: string }> {
  return fetchJson(`/templates/${encodeURIComponent(templateName)}/tools/${encodeURIComponent(filename)}`, { method: 'DELETE' });
}

export function runWeaveScript(
  templateName: string,
  script: string,
  args: Record<string, string> | undefined,
  onMessage: (data: { type: string; message: string }) => void,
): AbortController {
  const controller = new AbortController();
  fetch(`${BASE}/templates/${encodeURIComponent(templateName)}/run-script/${script}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ args: args || {} }),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok) {
      const detail = await res.text();
      onMessage({ type: 'error', message: `API error ${res.status}: ${detail}` });
      return;
    }
    const reader = res.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { onMessage(JSON.parse(line.slice(6))); } catch {}
        }
      }
    }
  }).catch((e) => {
    if (e.name !== 'AbortError') {
      onMessage({ type: 'error', message: e.message });
    }
  });
  return controller;
}

// --- Background Runs ---

export interface BackgroundRun {
  run_id: string;
  weave_dir_name: string;
  weave_name: string;
  script: string;
  slice_name: string;
  status: 'running' | 'done' | 'error' | 'interrupted' | 'unknown';
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
}

export function startBackgroundRun(
  templateName: string,
  script: string,
  args?: Record<string, string>,
): Promise<{ run_id: string; status: string }> {
  return fetchJson(`/templates/${encodeURIComponent(templateName)}/start-run/${script}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ args: args || {} }),
  });
}

export function listBackgroundRuns(): Promise<BackgroundRun[]> {
  return fetchJson('/templates/runs');
}

export function getBackgroundRun(runId: string): Promise<BackgroundRun> {
  return fetchJson(`/templates/runs/${encodeURIComponent(runId)}`);
}

export function getBackgroundRunOutput(
  runId: string,
  offset: number = 0,
): Promise<{ output: string; offset: number; status: string }> {
  return fetchJson(`/templates/runs/${encodeURIComponent(runId)}/output?offset=${offset}`);
}

export function stopBackgroundRun(runId: string): Promise<{ status: string }> {
  return fetchJson(`/templates/runs/${encodeURIComponent(runId)}/stop`, { method: 'POST' });
}

export function deleteBackgroundRun(runId: string): Promise<{ status: string }> {
  return fetchJson(`/templates/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' });
}

export function getWeaveLog(
  dirName: string,
  offset: number = 0,
): Promise<{ output: string; offset: number }> {
  return fetchJson(`/templates/${encodeURIComponent(dirName)}/weave-log?offset=${offset}`);
}

// --- VM Templates ---

export function listVmTemplates(): Promise<VMTemplateSummary[]> {
  return fetchJson('/vm-templates');
}

export function getVmTemplate(name: string): Promise<VMTemplateDetail> {
  return fetchJson(`/vm-templates/${encodeURIComponent(name)}`);
}

export function getVmTemplateVariant(name: string, image: string): Promise<VMTemplateVariantDetail> {
  return fetchJson(`/vm-templates/${encodeURIComponent(name)}/variant/${encodeURIComponent(image)}`);
}

export function saveVmTemplate(data: {
  name: string; description: string; image: string; boot_config: BootConfig;
  cores?: number; ram?: number; disk?: number; site?: string; host?: string;
  image_type?: string; username?: string; instance_type?: string;
  components?: Array<{ name: string; model: string }>;
}): Promise<VMTemplateDetail> {
  return fetchJson('/vm-templates', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function updateVmTemplate(name: string, data: { description?: string; image?: string; boot_config?: BootConfig }): Promise<VMTemplateDetail> {
  return fetchJson(`/vm-templates/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function deleteVmTemplate(name: string): Promise<{ status: string; name: string }> {
  return fetchJson(`/vm-templates/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function readVmTemplateTool(templateName: string, filename: string): Promise<{ filename: string; content: string }> {
  return fetchJson(`/vm-templates/${encodeURIComponent(templateName)}/tools/${encodeURIComponent(filename)}`);
}

export function writeVmTemplateTool(templateName: string, filename: string, content: string): Promise<{ filename: string; status: string }> {
  return fetchJson(`/vm-templates/${encodeURIComponent(templateName)}/tools/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export function deleteVmTemplateTool(templateName: string, filename: string): Promise<{ filename: string; status: string }> {
  return fetchJson(`/vm-templates/${encodeURIComponent(templateName)}/tools/${encodeURIComponent(filename)}`, { method: 'DELETE' });
}

// --- Resources ---

export function listSites(maxAge?: number): Promise<SiteInfo[]> {
  const params = maxAge !== undefined ? `?max_age=${maxAge}` : '';
  return fetchJson(`/sites${params}`);
}

export function listLinks(maxAge?: number): Promise<LinkInfo[]> {
  const params = maxAge !== undefined ? `?max_age=${maxAge}` : '';
  return fetchJson(`/links${params}`);
}

export function listFacilityPorts(maxAge?: number): Promise<FacilityPortInfo[]> {
  const params = maxAge !== undefined ? `?max_age=${maxAge}` : '';
  return fetchJson(`/facility-ports${params}`);
}

export function getSiteDetail(name: string): Promise<SiteDetail> {
  return fetchJson(`/sites/${encodeURIComponent(name)}`);
}

export function listSiteHosts(siteName: string): Promise<HostInfo[]> {
  return fetchJson(`/sites/${encodeURIComponent(siteName)}/hosts`);
}

export function resolveSites(sliceName: string, overrides?: Record<string, string>, resolveAll?: boolean): Promise<SliceData> {
  return fetchJson(`/slices/${encodeURIComponent(sliceName)}/resolve-sites`, {
    method: 'POST',
    body: JSON.stringify({ group_overrides: overrides || {}, resolve_all: resolveAll || false }),
  });
}

export function getSiteMetrics(name: string): Promise<SiteMetrics> {
  return fetchJson(`/metrics/site/${encodeURIComponent(name)}`);
}

export function getLinkMetrics(siteA: string, siteB: string): Promise<LinkMetrics> {
  return fetchJson(`/metrics/link/${encodeURIComponent(siteA)}/${encodeURIComponent(siteB)}`);
}

export function listImages(): Promise<string[]> {
  return fetchJson('/images');
}

export function listComponentModels(): Promise<ComponentModel[]> {
  return fetchJson('/component-models');
}

// --- Config ---

export function getConfig(): Promise<ConfigStatus> {
  return fetchJson('/config');
}

export function getAiTools(): Promise<Record<string, boolean>> {
  return fetchJson('/config/ai-tools');
}

export interface AIModelEntry { id: string; name: string; healthy?: boolean; }
export interface AIModelsResponse {
  fabric: AIModelEntry[];
  nrp: AIModelEntry[];
  default: string;
  has_key: { fabric: boolean; nrp: boolean };
  models: string[];       // backward compat
  nrp_models: string[];   // backward compat
}
export function getAiModels(): Promise<AIModelsResponse> {
  return fetchJson('/ai/models');
}

export function getDefaultModel(): Promise<{ default: string; source: string }> {
  return fetchJson('/ai/models/default');
}

export function setDefaultModel(model: string, source?: string): Promise<{ default: string; source: string }> {
  return fetchJson('/ai/models/default', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, source: source || '' }),
  });
}

export function testModelHealth(model: string, source?: string): Promise<{ healthy: boolean; latency_ms: number; error: string; model: string; source: string }> {
  return fetchJson('/ai/models/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, source: source || 'fabric' }),
  });
}

export function refreshModelHealth(): Promise<AIModelsResponse> {
  return fetchJson('/ai/models/refresh', { method: 'POST' });
}

// --- Chameleon Cloud ---

import type { ChameleonSite, ChameleonLease, ChameleonInstance, ChameleonImage, ChameleonStatus, ChameleonTestResult, ChameleonNetwork, ChameleonNodeTypeDetail, ChameleonDraft, ChameleonSlice } from '../types/chameleon';

export function getChameleonStatus(): Promise<ChameleonStatus> {
  return fetchJson('/chameleon/status');
}

export function getChameleonSites(): Promise<ChameleonSite[]> {
  return fetchJson('/chameleon/sites');
}

export function getChameleonAvailability(site: string): Promise<{ hosts: any[]; flavors: any[]; site: string }> {
  return fetchJson(`/chameleon/sites/${encodeURIComponent(site)}/availability`);
}

export function getChameleonNodeTypes(site: string): Promise<{ site: string; node_types: Array<{ node_type: string; total: number; reservable: number; cpu_arch: string }> }> {
  return fetchJson(`/chameleon/sites/${encodeURIComponent(site)}/node-types`);
}

export function getChameleonImages(site: string): Promise<ChameleonImage[]> {
  return fetchJson(`/chameleon/sites/${encodeURIComponent(site)}/images`);
}

export function listChameleonLeases(site?: string): Promise<ChameleonLease[]> {
  const params = site ? `?site=${encodeURIComponent(site)}` : '';
  return fetchJson(`/chameleon/leases${params}`);
}

export function getChameleonLease(leaseId: string, site: string): Promise<ChameleonLease> {
  return fetchJson(`/chameleon/leases/${leaseId}?site=${encodeURIComponent(site)}`);
}

export function createChameleonLease(params: { site: string; name: string; node_type: string; node_count: number; duration_hours: number }): Promise<ChameleonLease> {
  return fetchJson('/chameleon/leases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
}

export function extendChameleonLease(leaseId: string, site: string, hours: number): Promise<ChameleonLease> {
  return fetchJson(`/chameleon/leases/${leaseId}/extend`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site, hours }),
  });
}

export function deleteChameleonLease(leaseId: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/leases/${leaseId}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}

export function listChameleonInstances(site?: string): Promise<ChameleonInstance[]> {
  const params = site ? `?site=${encodeURIComponent(site)}` : '';
  return fetchJson(`/chameleon/instances${params}`);
}

export function createChameleonInstance(params: { site: string; name: string; lease_id: string; reservation_id?: string; image_id: string; key_name?: string; network_id?: string }): Promise<ChameleonInstance> {
  return fetchJson('/chameleon/instances', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
}

export function deleteChameleonInstance(instanceId: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/instances/${instanceId}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}

export function getChameleonSliceNodes(sliceName: string): Promise<Array<{ name: string; site: string; node_type: string; image_id?: string; connection_type?: string; status?: string }>> {
  return fetchJson(`/chameleon/slice-nodes/${encodeURIComponent(sliceName)}`);
}

export function addChameleonSliceNode(sliceName: string, node: { name: string; site: string; node_type: string; image_id?: string; connection_type?: string; vlan?: string; fabric_site?: string }): Promise<{ chameleon_nodes: any[] }> {
  return fetchJson(`/chameleon/slice-nodes/${encodeURIComponent(sliceName)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(node),
  });
}

export function removeChameleonSliceNode(sliceName: string, nodeName: string): Promise<{ chameleon_nodes: any[] }> {
  return fetchJson(`/chameleon/slice-nodes/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}`, { method: 'DELETE' });
}

export function findChameleonAvailability(params: { site: string; node_type: string; node_count: number; duration_hours: number }): Promise<{ earliest_start: string | null; available_now: number; total: number; error: string }> {
  return fetchJson('/chameleon/find-availability', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
}

export function getChameleonGraph(): Promise<{ nodes: any[]; edges: any[] }> {
  return fetchJson('/chameleon/graph');
}

export function testChameleonConnection(site: string): Promise<Record<string, ChameleonTestResult>> {
  return fetchJson('/chameleon/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site }),
  });
}

// Instance actions
export function rebootChameleonInstance(instanceId: string, site: string, type?: string): Promise<{ status: string }> {
  return fetchJson(`/chameleon/instances/${instanceId}/reboot`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site, type: type || 'SOFT' }),
  });
}

export function stopChameleonInstance(instanceId: string, site: string): Promise<{ status: string }> {
  return fetchJson(`/chameleon/instances/${instanceId}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site }),
  });
}

export function startChameleonInstance(instanceId: string, site: string): Promise<{ status: string }> {
  return fetchJson(`/chameleon/instances/${instanceId}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site }),
  });
}

export function assignChameleonFloatingIp(instanceId: string, site: string): Promise<{ instance_id: string; floating_ip: string; fip_id: string }> {
  return fetchJson(`/chameleon/instances/${instanceId}/associate-ip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site }),
  });
}

export function disassociateChameleonIp(instanceId: string, site: string, floatingIp: string): Promise<{ status: string }> {
  return fetchJson(`/chameleon/instances/${instanceId}/disassociate-ip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site, floating_ip: floatingIp }),
  });
}

// Networks
export function listChameleonNetworks(site?: string): Promise<ChameleonNetwork[]> {
  const params = site ? `?site=${encodeURIComponent(site)}` : '';
  return fetchJson(`/chameleon/networks${params}`);
}

export function createChameleonNetwork(params: { site: string; name: string; cidr?: string }): Promise<ChameleonNetwork> {
  return fetchJson('/chameleon/networks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
}

export function deleteChameleonNetwork(networkId: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/networks/${networkId}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}

// OpenStack resources — key pairs, floating IPs, security groups
export function ensureChameleonNetwork(site: string): Promise<{ network_id: string; network_name: string; type: string }> {
  return fetchJson(`/chameleon/sites/${encodeURIComponent(site)}/ensure-network`, { method: 'POST' });
}

export function ensureChameleonBastion(sliceId: string, params: { site: string; experiment_net_id?: string; reservation_id?: string }): Promise<{ status: string; instance_id: string; floating_ip: string; site: string }> {
  return fetchJson(`/chameleon/slices/${sliceId}/ensure-bastion`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
}

export function importChameleonReservation(sliceId: string, site: string, leaseId: string): Promise<any> {
  return fetchJson(`/chameleon/slices/${sliceId}/import-reservation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site, lease_id: leaseId }),
  });
}

export function ensureChameleonKeypair(site: string): Promise<{ name: string; status: string; key_path: string }> {
  return fetchJson('/chameleon/keypairs/ensure', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site }),
  });
}

export function listChameleonKeypairs(site?: string): Promise<any[]> {
  return fetchJson(`/chameleon/keypairs${site ? '?site=' + encodeURIComponent(site) : ''}`);
}
export function createChameleonKeypair(params: { site: string; name: string; public_key?: string }): Promise<any> {
  return fetchJson('/chameleon/keypairs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
}
export function deleteChameleonKeypair(name: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/keypairs/${encodeURIComponent(name)}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}
export function listChameleonFloatingIps(site?: string): Promise<any[]> {
  return fetchJson(`/chameleon/floating-ips${site ? '?site=' + encodeURIComponent(site) : ''}`);
}
export function listChameleonSecurityGroups(site?: string): Promise<any[]> {
  return fetchJson(`/chameleon/security-groups${site ? '?site=' + encodeURIComponent(site) : ''}`);
}
export function deleteChameleonSecurityGroup(sgId: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/security-groups/${encodeURIComponent(sgId)}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}
export function allocateChameleonFloatingIp(site: string, network?: string): Promise<any> {
  return fetchJson('/chameleon/floating-ips', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ site, network: network || 'public' }) });
}
export function releaseChameleonFloatingIp(ipId: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/floating-ips/${encodeURIComponent(ipId)}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}
export function associateChameleonFloatingIp(ipId: string, site: string, portId: string): Promise<any> {
  return fetchJson(`/chameleon/floating-ips/${encodeURIComponent(ipId)}/associate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ site, port_id: portId }) });
}
export function createChameleonSecurityGroup(params: { site: string; name: string; description?: string }): Promise<any> {
  return fetchJson('/chameleon/security-groups', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
}
export function addChameleonSecurityGroupRule(sgId: string, rule: { site: string; direction: string; protocol?: string; port_range_min?: number; port_range_max?: number; remote_ip_prefix?: string; ethertype?: string }): Promise<any> {
  return fetchJson(`/chameleon/security-groups/${encodeURIComponent(sgId)}/rules`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rule) });
}
export function deleteChameleonSecurityGroupRule(sgId: string, ruleId: string, site: string): Promise<void> {
  return fetchJson(`/chameleon/security-groups/${encodeURIComponent(sgId)}/rules/${encodeURIComponent(ruleId)}?site=${encodeURIComponent(site)}`, { method: 'DELETE' });
}

// Enhanced node types with hardware detail
export function getChameleonNodeTypesDetail(site: string): Promise<{ site: string; node_types: ChameleonNodeTypeDetail[] }> {
  return fetchJson(`/chameleon/sites/${encodeURIComponent(site)}/node-types?detail=true`);
}

// Schedule calendar
export interface ChameleonCalendarData {
  time_range: { start: string; end: string };
  sites: Array<{
    name: string;
    node_types: Array<{ node_type: string; total: number; reservable: number }>;
    leases: ChameleonLease[];
  }>;
}

export function getChameleonScheduleCalendar(days?: number): Promise<ChameleonCalendarData> {
  const params = days !== undefined ? `?days=${days}` : '';
  return fetchJson(`/chameleon/schedule/calendar${params}`);
}

// --- Chameleon Drafts ---

export function listChameleonDrafts(): Promise<ChameleonDraft[]> {
  return fetchJson('/chameleon/drafts');
}

export function createChameleonDraft(params: { name: string; site?: string }): Promise<ChameleonDraft> {
  return fetchJson('/chameleon/drafts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
}

export function getChameleonDraft(draftId: string): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}`);
}

export function deleteChameleonDraft(draftId: string, deleteResources: boolean = false): Promise<{ status: string; draft_id: string; cleanup_errors?: string[] }> {
  const params = deleteResources ? '?delete_resources=true' : '';
  return fetchJson(`/chameleon/drafts/${draftId}${params}`, { method: 'DELETE' });
}

export function addChameleonDraftNode(draftId: string, node: { name: string; node_type: string; image: string; count?: number; site: string }): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}/nodes`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(node) });
}

export function removeChameleonDraftNode(draftId: string, nodeId: string): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}/nodes/${nodeId}`, { method: 'DELETE' });
}

export function updateChameleonNodeNetwork(draftId: string, nodeId: string, network: { id: string; name: string } | null): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}/nodes/${nodeId}/network`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(network) });
}

export function updateChameleonNodeInterfaces(draftId: string, nodeId: string, interfaces: Array<{ nic: number; network: { id: string; name: string } | null }>): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}/nodes/${nodeId}/interfaces`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(interfaces) });
}

export function addChameleonDraftNetwork(draftId: string, net: { name: string; connected_nodes: string[] }): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}/networks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(net) });
}

export function removeChameleonDraftNetwork(draftId: string, networkId: string): Promise<ChameleonDraft> {
  return fetchJson(`/chameleon/drafts/${draftId}/networks/${networkId}`, { method: 'DELETE' });
}

export function deployChameleonDraft(draftId: string, params: { lease_name?: string; duration_hours?: number; start_date?: string }): Promise<import('../types/chameleon').ChameleonDeployResult> {
  return fetchJson(`/chameleon/drafts/${draftId}/deploy`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
}

export function getChameleonDraftGraph(draftId: string): Promise<{ nodes: any[]; edges: any[] }> {
  return fetchJson(`/chameleon/drafts/${draftId}/graph`);
}

// --- Chameleon Slices ---

export function listChameleonSlices(): Promise<ChameleonSlice[]> {
  return fetchJson('/chameleon/slices');
}

export function listAllChameleonSlices(): Promise<ChameleonSlice[]> {
  return fetchJson('/chameleon/slices');
}

export function createChameleonSlice(params: { name: string; site: string }): Promise<ChameleonSlice> {
  return fetchJson('/chameleon/slices', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
}

export function deleteChameleonSlice(sliceId: string): Promise<void> {
  return fetchJson(`/chameleon/slices/${sliceId}`, { method: 'DELETE' });
}

export function addChameleonSliceResource(sliceId: string, resource: { type: string; id?: string; name?: string; site?: string; [key: string]: any }): Promise<ChameleonSlice> {
  return fetchJson(`/chameleon/slices/${sliceId}/add-resource`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(resource) });
}

export function removeChameleonSliceResource(sliceId: string, resourceId: string): Promise<ChameleonSlice> {
  return fetchJson(`/chameleon/slices/${sliceId}/remove-resource`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resource_id: resourceId }) });
}

export function setChameleonSliceState(sliceId: string, state: string): Promise<ChameleonSlice> {
  return fetchJson(`/chameleon/slices/${sliceId}/state`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state }),
  });
}

export function listUnaffiliatedChameleonInstances(): Promise<ChameleonInstance[]> {
  return fetchJson('/chameleon/instances/unaffiliated');
}

export function executeChameleonRecipe(instanceId: string, site: string, recipeDirName: string): Promise<{ status: string }> {
  return fetchJson(`/chameleon/instances/${instanceId}/execute-recipe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ site, recipe_dir: recipeDirName }),
  });
}

export function executeChameleonBootConfig(sliceId: string, nodeName: string): Promise<{ status: string }> {
  return fetchJson(`/chameleon/boot-config/${encodeURIComponent(sliceId)}/${encodeURIComponent(nodeName)}/execute`, { method: 'POST' });
}

export function getChameleonBootConfig(sliceId: string, nodeName: string): Promise<any> {
  return fetchJson(`/chameleon/boot-config/${encodeURIComponent(sliceId)}/${encodeURIComponent(nodeName)}`);
}

export function saveChameleonBootConfig(sliceId: string, nodeName: string, config: any): Promise<any> {
  return fetchJson(`/chameleon/boot-config/${encodeURIComponent(sliceId)}/${encodeURIComponent(nodeName)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function getChameleonSliceGraph(sliceId: string): Promise<{ nodes: any[]; edges: any[] }> {
  return fetchJson(`/chameleon/slices/${sliceId}/graph`);
}

export function setDraftFloatingIps(draftId: string, entries: Array<{ node_id: string; nic: number }>): Promise<ChameleonSlice> {
  return fetchJson(`/chameleon/drafts/${draftId}/floating-ips`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entries }),
  });
}

export function autoNetworkSetup(sliceId: string): Promise<{ results: Array<{ name: string; site: string; floating_ip?: string; error?: string; status?: string }> }> {
  return fetchJson(`/chameleon/slices/${sliceId}/auto-network-setup`, { method: 'POST' });
}

export function checkSliceReadiness(sliceId: string): Promise<{ results: Array<{ name: string; site: string; instance_id: string; ip: string; ssh_ready: boolean }> }> {
  return fetchJson(`/chameleon/slices/${sliceId}/check-readiness`, { method: 'POST' });
}

// --- VLAN Negotiation ---

export interface VlanNegotiationResult {
  fabric_site: string;
  chameleon_site: string;
  fabric_vlans: number[];
  chameleon_vlans: number[];
  common_vlans: number[];
  suggested_vlan: number | null;
  error?: string;
}

export function negotiateChameleonVlan(fabricSite: string, chameleonSite: string): Promise<VlanNegotiationResult> {
  return fetchJson('/chameleon/negotiate-vlan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fabric_site: fabricSite, chameleon_site: chameleonSite }),
  });
}

// --- Composite Slice Submit ---

export function submitCompositeSlice(name: string): Promise<{
  status: string;
  fabric_status: string;
  chameleon_lease_id?: string;
  chameleon_status?: string;
  fabric_slice?: SliceData;
  fabric_error?: string;
  chameleon_error?: string;
}> {
  return fetchJson(`/slices/${encodeURIComponent(name)}/submit-composite`, { method: 'POST' });
}

// --- Composite Slice Management ---

export function listCompositeSlices(): Promise<any[]> {
  return fetchJson('/composite/slices');
}

export function getCompositeSlice(id: string): Promise<any> {
  return fetchJson(`/composite/slices/${encodeURIComponent(id)}`);
}

export function createCompositeSlice(name: string): Promise<any> {
  return fetchJson('/composite/slices', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
}

export function deleteCompositeSlice(id: string): Promise<any> {
  return fetchJson(`/composite/slices/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function updateCompositeMembers(compositeId: string, fabricSlices: string[], chameleonSlices: string[]): Promise<any> {
  return fetchJson(`/composite/slices/${encodeURIComponent(compositeId)}/members`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fabric_slices: fabricSlices, chameleon_slices: chameleonSlices }) });
}

export function replaceCompositeFabricMember(oldId: string, newId: string): Promise<any> {
  return fetchJson('/composite/replace-fabric-member', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ old_id: oldId, new_id: newId }) });
}

export function updateCompositeCrossConnections(compositeId: string, connections: any[]): Promise<any> {
  return fetchJson(`/composite/slices/${encodeURIComponent(compositeId)}/cross-connections`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(connections) });
}

export function getCompositeGraph(compositeId: string): Promise<{ nodes: any[]; edges: any[] }> {
  return fetchJson(`/composite/slices/${encodeURIComponent(compositeId)}/graph`);
}

export function submitCompositeSliceById(compositeId: string, leaseHours = 24): Promise<any> {
  return fetchJson(`/composite/slices/${encodeURIComponent(compositeId)}/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lease_hours: leaseHours }) });
}

export function getViewsStatus(): Promise<{ fabric_enabled: boolean; chameleon_enabled: boolean; composite_enabled: boolean }> {
  return fetchJson('/views/status');
}

// --- Trovi Marketplace ---

export interface TroviArtifact {
  uuid: string;
  title: string;
  short_description: string;
  tags: string[];
  authors: string[];
  created_at: string;
  updated_at: string;
  visibility: string;
  versions: number;
  source: 'trovi';
}

export function listTroviArtifacts(q?: string, tag?: string): Promise<{ artifacts: TroviArtifact[]; total: number }> {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (tag) params.set('tag', tag);
  const qs = params.toString();
  return fetchJson(`/trovi/artifacts${qs ? '?' + qs : ''}`);
}

export function getTroviArtifact(uuid: string): Promise<any> {
  return fetchJson(`/trovi/artifacts/${uuid}`);
}

export function getTroviTags(): Promise<{ tags: string[] }> {
  return fetchJson('/trovi/tags');
}

export function downloadTroviArtifact(uuid: string): Promise<{ status: string; dir_name: string; title: string }> {
  return fetchJson(`/trovi/artifacts/${uuid}/get`, { method: 'POST' });
}

// --- AI Tool Install Status ---

export interface ToolInstallInfo {
  installed: boolean;
  display_name: string;
  size_estimate: string;
  type: string;
}

export function getToolInstallStatus(): Promise<Record<string, ToolInstallInfo>> {
  return fetchJson('/ai/tools/status');
}

export function installTool(toolId: string): Promise<{ status: string; tool: string; output?: string; error?: string }> {
  return fetchJson(`/ai/tools/${encodeURIComponent(toolId)}/install`, { method: 'POST' });
}

export interface InstallStreamEvent {
  type: 'start' | 'output' | 'done' | 'error';
  tool?: string;
  display_name?: string;
  size_estimate?: string;
  message?: string;
  status?: string;
}

export async function installToolStream(
  toolId: string,
  onEvent: (event: InstallStreamEvent) => void,
): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/ai/tools/${encodeURIComponent(toolId)}/install-stream`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Install stream error ${res.status}`);
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalStatus = 'error';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event: InstallStreamEvent = JSON.parse(line.slice(6));
          onEvent(event);
          if (event.type === 'done' && event.status) {
            finalStatus = event.status;
          }
        } catch {}
      }
    }
  }
  return { status: finalStatus };
}

export function startOpenCodeWeb(model?: string): Promise<{ port?: number; status: string; error?: string; install_required?: boolean; tool?: string }> {
  const params = model ? `?model=${encodeURIComponent(model)}` : '';
  return fetchJson(`/ai/opencode-web/start${params}`, { method: 'POST' });
}

export function stopOpenCodeWeb(): Promise<{ status: string }> {
  return fetchJson('/ai/opencode-web/stop', { method: 'POST' });
}

export function getOpenCodeWebStatus(): Promise<{ port?: number; status: string }> {
  return fetchJson('/ai/opencode-web/status');
}

export function startAiderWeb(model?: string): Promise<{ port?: number; status: string; error?: string; install_required?: boolean; tool?: string }> {
  const params = model ? `?model=${encodeURIComponent(model)}` : '';
  return fetchJson(`/ai/aider-web/start${params}`, { method: 'POST' });
}

export function stopAiderWeb(): Promise<{ status: string }> {
  return fetchJson('/ai/aider-web/stop', { method: 'POST' });
}

export function getAiderWebStatus(): Promise<{ port?: number; status: string }> {
  return fetchJson('/ai/aider-web/status');
}

export function setAiTools(tools: Record<string, boolean>): Promise<Record<string, boolean>> {
  return fetchJson('/config/ai-tools', { method: 'POST', body: JSON.stringify(tools) });
}

// --- JupyterLab ---

export function startJupyter(): Promise<{ port?: number; status: string; error?: string; install_required?: boolean; tool?: string }> {
  return fetchJson('/jupyter/start', { method: 'POST' });
}

export function stopJupyter(): Promise<{ status: string }> {
  return fetchJson('/jupyter/stop', { method: 'POST' });
}

export function getJupyterStatus(): Promise<{ port?: number; status: string }> {
  return fetchJson('/jupyter/status');
}

export function setJupyterTheme(theme: 'dark' | 'light'): Promise<{ status: string }> {
  return fetchJson('/jupyter/theme', { method: 'POST', body: JSON.stringify({ theme }) });
}

// --- People search ---

export interface PersonSearchResult {
  uuid: string;
  name: string;
  email: string;
  affiliation: string;
}

export function searchPeople(query: string): Promise<{ results: PersonSearchResult[] }> {
  return fetchJson(`/people/search?q=${encodeURIComponent(query)}`);
}

// --- Notebook artifacts ---

export function launchNotebook(name: string): Promise<{
  status: string;
  port?: number;
  jupyter_path?: string;
  work_dir?: string;
  has_working_copy?: boolean;
  error?: string;
}> {
  return fetchJson(`/notebooks/${encodeURIComponent(name)}/launch`, { method: 'POST' });
}

export function resetNotebook(name: string): Promise<{ status: string; name: string }> {
  return fetchJson(`/notebooks/${encodeURIComponent(name)}/reset`, { method: 'POST' });
}

export function getNotebookStatus(name: string): Promise<{
  name: string;
  has_workspace: boolean;
  has_original: boolean;
}> {
  return fetchJson(`/notebooks/${encodeURIComponent(name)}/status`);
}

export function publishNotebookFork(name: string, params: {
  title: string;
  description?: string;
  description_long?: string;
  visibility?: string;
  project_uuid?: string;
  tags?: string[];
}): Promise<{
  status: string;
  uuid: string;
  title: string;
  forked_from?: string;
}> {
  return fetchJson(`/notebooks/${encodeURIComponent(name)}/publish-fork`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

// --- Artifact Marketplace ---

export interface RemoteArtifact {
  uuid: string;
  title: string;
  description_short: string;
  description_long?: string;
  visibility: string;
  tags: string[];
  category: string;
  authors: { name: string; affiliation: string }[];
  versions: { uuid: string; version: string; urn: string; active: boolean; created: string; version_downloads: number }[];
  project_uuid?: string;
  project_name?: string;
  artifact_views: number;
  artifact_downloads_active: number;
  number_of_versions: number;
  created: string;
  modified: string;
}

export interface TagInfo {
  name: string;
  count: number;
}

export interface RemoteArtifactsResponse {
  artifacts: RemoteArtifact[];
  total_count: number;
  tags: TagInfo[];
}

export function listRemoteArtifacts(): Promise<RemoteArtifactsResponse> {
  return fetchJson('/artifacts/remote');
}

export function refreshRemoteArtifacts(): Promise<RemoteArtifactsResponse> {
  return fetchJson('/artifacts/remote/refresh', { method: 'POST' });
}

export function downloadArtifact(uuid: string, versionUuid?: string, localName?: string, overwrite?: boolean): Promise<{
  status: string;
  title: string;
  category: string;
  local_name: string;
}> {
  return fetchJson('/artifacts/download', {
    method: 'POST',
    body: JSON.stringify({
      uuid,
      version_uuid: versionUuid || '',
      local_name: localName || '',
      overwrite: overwrite || false,
    }),
  });
}

export interface ValidTag {
  tag: string;
  restricted: boolean;
}

export function publishArtifact(params: {
  dir_name: string;
  category: string;
  title: string;
  description?: string;
  description_long?: string;
  tags?: string[];
  visibility?: string;
  project_uuid?: string;
  authors?: { name: string; affiliation: string }[];
  action?: 'update' | 'fork';
}): Promise<{
  status: string;
  uuid: string;
  title: string;
  visibility: string;
  version: string;
  forked_from?: string;
}> {
  return fetchJson('/artifacts/publish', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export interface PublishInfo {
  can_update: boolean;
  can_fork: boolean;
  is_author: boolean;
  artifact_uuid: string | null;
  remote_title: string | null;
}

export function getPublishInfo(dirName: string): Promise<PublishInfo> {
  return fetchJson(`/artifacts/local/${encodeURIComponent(dirName)}/publish-info`);
}

let _validTagsCache: Promise<{ tags: ValidTag[] }> | null = null;

export function listValidTags(): Promise<{ tags: ValidTag[] }> {
  if (!_validTagsCache) {
    _validTagsCache = fetchJson('/artifacts/valid-tags');
    _validTagsCache.catch(() => { _validTagsCache = null; });
  }
  return _validTagsCache;
}

// --- My Artifacts (annotated local + authorship) ---

export interface LocalArtifact {
  name: string;
  description: string;
  description_short?: string;
  description_long?: string;
  source: string;
  artifact_uuid?: string;
  version_uuid?: string;
  version?: string;
  created: string;
  tags: string[];
  dir_name: string;
  category: string;
  is_experiment?: boolean;
  is_from_marketplace: boolean;
  remote_status?: 'linked' | 'not_linked' | 'remote_deleted' | 'check_failed';
  is_author?: boolean;
  remote_artifact?: RemoteArtifact | null;
  update_available?: boolean;
  latest_version?: string;
}

export interface MyArtifactsResponse {
  local_artifacts: LocalArtifact[];
  authored_remote_only: RemoteArtifact[];
  user_email: string;
}

let _myArtifactsPromise: Promise<MyArtifactsResponse> | null = null;
let _myArtifactsTime = 0;
const MY_ARTIFACTS_TTL = 5000; // 5s dedup window

export function getMyArtifacts(): Promise<MyArtifactsResponse> {
  const now = Date.now();
  if (_myArtifactsPromise && (now - _myArtifactsTime) < MY_ARTIFACTS_TTL) {
    return _myArtifactsPromise;
  }
  _myArtifactsTime = now;
  _myArtifactsPromise = fetchJson('/artifacts/my');
  _myArtifactsPromise.catch(() => { _myArtifactsPromise = null; });
  return _myArtifactsPromise;
}

export function updateLocalArtifactMetadata(dirName: string, params: {
  name?: string;
  description?: string;
  description_short?: string;
  description_long?: string;
  tags?: string[];
  authors?: string[];
  project_uuid?: string;
  visibility?: string;
}): Promise<{ status: string; metadata: Record<string, unknown> }> {
  return fetchJson(`/artifacts/local/${encodeURIComponent(dirName)}/metadata`, {
    method: 'PUT',
    body: JSON.stringify(params),
  });
}

export function updateRemoteArtifact(uuid: string, params: {
  title?: string;
  description?: string;
  description_long?: string;
  visibility?: string;
  tags?: string[];
  project_uuid?: string;
  authors?: { name: string; affiliation: string }[];
  category?: string;
}): Promise<RemoteArtifact> {
  return fetchJson(`/artifacts/remote/${uuid}`, {
    method: 'PUT',
    body: JSON.stringify(params),
  });
}

export function uploadArtifactVersion(uuid: string, dirName: string, category: string): Promise<{
  status: string;
  version: string;
  artifact_uuid: string;
}> {
  return fetchJson(`/artifacts/remote/${uuid}/version`, {
    method: 'POST',
    body: JSON.stringify({ artifact_uuid: uuid, dir_name: dirName, category }),
  });
}

export function deleteRemoteArtifact(uuid: string): Promise<{ status: string; uuid: string }> {
  return fetchJson(`/artifacts/remote/${uuid}`, { method: 'DELETE' });
}

export function deleteArtifactVersion(uuid: string, versionUuid: string): Promise<{ status: string; uuid: string; version_uuid: string }> {
  return fetchJson(`/artifacts/remote/${uuid}/version/${versionUuid}`, { method: 'DELETE' });
}

export function revertArtifact(dirName: string, versionUuid?: string): Promise<{
  status: string;
  dir_name: string;
  version: string;
  category: string;
}> {
  return fetchJson(`/artifacts/local/${encodeURIComponent(dirName)}/revert`, {
    method: 'POST',
    body: JSON.stringify({ version_uuid: versionUuid || null }),
  });
}

// --- AI Agents & Skills ---

export interface AgentDetail {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'custom' | 'customized';
  content?: string;
}

export interface SkillDetail {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'custom' | 'customized';
  content?: string;
}

export function getAgents(): Promise<AgentDetail[]> {
  return fetchJson('/ai/agents');
}
export function getAgent(id: string): Promise<AgentDetail> {
  return fetchJson(`/ai/agents/${encodeURIComponent(id)}`);
}
export function saveAgent(id: string, data: { name: string; description: string; content: string }): Promise<AgentDetail> {
  return fetchJson(`/ai/agents/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) });
}
export function deleteAgent(id: string): Promise<{ status: string }> {
  return fetchJson(`/ai/agents/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export function resetAgent(id: string): Promise<AgentDetail> {
  return fetchJson(`/ai/agents/${encodeURIComponent(id)}/reset`, { method: 'POST' });
}

export function getSkills(): Promise<SkillDetail[]> {
  return fetchJson('/ai/skills');
}
export function getSkill(id: string): Promise<SkillDetail> {
  return fetchJson(`/ai/skills/${encodeURIComponent(id)}`);
}
export function saveSkill(id: string, data: { name: string; description: string; content: string }): Promise<SkillDetail> {
  return fetchJson(`/ai/skills/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(data) });
}
export function deleteSkill(id: string): Promise<{ status: string }> {
  return fetchJson(`/ai/skills/${encodeURIComponent(id)}`, { method: 'DELETE' });
}
export function resetSkill(id: string): Promise<SkillDetail> {
  return fetchJson(`/ai/skills/${encodeURIComponent(id)}/reset`, { method: 'POST' });
}

// --- AI Chat ---

export interface ChatAgent {
  id: string;
  name: string;
  description: string;
}

export function getChatAgents(): Promise<ChatAgent[]> {
  return fetchJson('/ai/chat/agents');
}

export function stopChatStream(requestId: string): Promise<{ status: string }> {
  return fetchJson('/ai/chat/stop', { method: 'POST', body: JSON.stringify({ request_id: requestId }) });
}

export async function* streamChat(
  messages: Array<{ role: string; content: string }>,
  model: string,
  options?: { agent?: string; sliceContext?: string; requestId?: string; signal?: AbortSignal },
): AsyncGenerator<{ content?: string; error?: string; done?: boolean }> {
  const res = await fetch(`${BASE}/ai/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages,
      model,
      agent: options?.agent,
      slice_context: options?.sliceContext,
      request_id: options?.requestId,
    }),
    signal: options?.signal,
  });
  if (!res.ok) {
    yield { error: `API error ${res.status}` };
    return;
  }
  const reader = res.body?.getReader();
  if (!reader) { yield { error: 'No response body' }; return; }
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const data = line.slice(6);
      if (data === '[DONE]') { yield { done: true }; return; }
      try { yield JSON.parse(data); } catch { /* skip */ }
    }
  }
}

export async function uploadToken(file: File): Promise<{ status: string; message: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/config/token`, { method: 'POST', body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

export function getLoginUrl(): Promise<{ login_url: string }> {
  const origin = typeof window !== 'undefined' ? window.location.origin : '';
  return fetchJson(`/config/login?origin=${encodeURIComponent(origin)}`);
}

export interface AutoSetupResponse {
  status: string;
  email: string;
  name: string;
  uuid: string;
  project_id: string;
  bastion_username: string;
  bastion_key_generated: boolean;
  slice_keys_generated: boolean;
  llm_key_created: boolean;
  llm_key_error: string;
}

export function autoSetup(projectId: string): Promise<AutoSetupResponse> {
  return fetchJson('/config/auto-setup', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  });
}

export function pasteToken(tokenText: string): Promise<{ status: string; message: string }> {
  return fetchJson('/config/token/paste', {
    method: 'POST',
    body: JSON.stringify({ token_text: tokenText }),
  });
}

export function getProjects(): Promise<ProjectsResponse> {
  return fetchJson('/config/projects');
}

export async function uploadBastionKey(file: File): Promise<{ status: string; message: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/config/keys/bastion`, { method: 'POST', body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

export async function uploadSliceKeys(
  privateKey: File,
  publicKey: File,
  keyName = 'default',
): Promise<{ status: string; message: string }> {
  const form = new FormData();
  form.append('private_key', privateKey);
  form.append('public_key', publicKey);
  const res = await fetch(`${BASE}/config/keys/slice?key_name=${encodeURIComponent(keyName)}`, { method: 'POST', body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

export function generateSliceKeys(keyName = 'default'): Promise<{ status: string; public_key: string; message: string }> {
  return fetchJson(`/config/keys/slice/generate?key_name=${encodeURIComponent(keyName)}`, { method: 'POST' });
}

// --- Slice Key Sets ---

export function listSliceKeySets(): Promise<SliceKeySet[]> {
  return fetchJson('/config/keys/slice/list');
}

export async function uploadSliceKeysNamed(
  privateKey: File,
  publicKey: File,
  keyName: string,
): Promise<{ status: string; message: string }> {
  const form = new FormData();
  form.append('private_key', privateKey);
  form.append('public_key', publicKey);
  const res = await fetch(`${BASE}/config/keys/slice?key_name=${encodeURIComponent(keyName)}`, { method: 'POST', body: form });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

export function setDefaultSliceKey(name: string): Promise<{ status: string; default: string }> {
  return fetchJson(`/config/keys/slice/default?key_name=${encodeURIComponent(name)}`, { method: 'PUT' });
}

export function deleteSliceKeySet(name: string): Promise<{ status: string; deleted: string }> {
  return fetchJson(`/config/keys/slice/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function getSliceKeyAssignment(sliceName: string): Promise<{ slice_name: string; slice_key_id: string }> {
  return fetchJson(`/config/slice-key/${encodeURIComponent(sliceName)}`);
}

export function setSliceKeyAssignment(sliceName: string, keyId: string): Promise<{ status: string }> {
  return fetchJson(`/config/slice-key/${encodeURIComponent(sliceName)}`, {
    method: 'PUT',
    body: JSON.stringify({ slice_key_id: keyId }),
  });
}

// --- Files (container storage) ---

export function listFiles(path = ''): Promise<FileEntry[]> {
  return fetchJson(`/files?path=${encodeURIComponent(path)}`);
}

export async function uploadFiles(path: string, files: FileList | File[]): Promise<{ uploaded: string[] }> {
  const form = new FormData();
  for (const f of Array.from(files)) {
    form.append('files', f);
  }
  const res = await fetch(`${BASE}/files/upload?path=${encodeURIComponent(path)}`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

/** Upload files with explicit relative paths (for folder drag-and-drop). */
export async function uploadFilesWithPaths(path: string, entries: Array<{ file: File; relativePath: string }>): Promise<{ uploaded: string[] }> {
  const form = new FormData();
  for (const { file, relativePath } of entries) {
    form.append('files', file, relativePath);
  }
  const res = await fetch(`${BASE}/files/upload?path=${encodeURIComponent(path)}`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

export function createFolder(path: string, name: string): Promise<{ created: string }> {
  return fetchJson(`/files/mkdir?path=${encodeURIComponent(path)}`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

export async function downloadFile(path: string): Promise<void> {
  const url = `${BASE}/files/download?path=${encodeURIComponent(path)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = path.split('/').pop() || 'download';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

export async function downloadFolder(path: string): Promise<void> {
  const url = `${BASE}/files/download-folder?path=${encodeURIComponent(path)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const folderName = path.split('/').pop() || 'folder';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${folderName}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

export function deleteFile(path: string): Promise<{ deleted: string }> {
  return fetchJson(`/files?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
}

export function readFileContent(path: string): Promise<{ path: string; content: string }> {
  return fetchJson(`/files/content?path=${encodeURIComponent(path)}`);
}

export function writeFileContent(path: string, content: string): Promise<{ path: string; status: string }> {
  return fetchJson('/files/content', {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  });
}

// --- Files (VM SFTP) ---

export function listVmFiles(sliceName: string, nodeName: string, path = '/home'): Promise<FileEntry[]> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}?path=${encodeURIComponent(path)}`);
}

export function downloadVmFile(sliceName: string, nodeName: string, remotePath: string, destDir: string): Promise<{ downloaded: string; local_path: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/download`, {
    method: 'POST',
    body: JSON.stringify({ remote_path: remotePath, dest_dir: destDir }),
  });
}

export function uploadToVm(sliceName: string, nodeName: string, source: string, dest: string): Promise<{ uploaded: string; remote_path: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/upload`, {
    method: 'POST',
    body: JSON.stringify({ source, dest }),
  });
}

/** Upload files directly from the browser to a VM (bypassing container storage). */
export async function uploadDirectToVm(
  sliceName: string,
  nodeName: string,
  destPath: string,
  files: FileList | File[],
): Promise<{ uploaded: string[] }> {
  const form = new FormData();
  for (const f of Array.from(files)) {
    form.append('files', f);
  }
  const res = await fetch(
    `${BASE}/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/upload-direct?dest_path=${encodeURIComponent(destPath)}`,
    { method: 'POST', body: form },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

/** Upload files with explicit relative paths directly to a VM (for folder drag-and-drop). */
export async function uploadDirectToVmWithPaths(
  sliceName: string,
  nodeName: string,
  destPath: string,
  entries: Array<{ file: File; relativePath: string }>,
): Promise<{ uploaded: string[] }> {
  const form = new FormData();
  for (const { file, relativePath } of entries) {
    form.append('files', file, relativePath);
  }
  const res = await fetch(
    `${BASE}/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/upload-direct?dest_path=${encodeURIComponent(destPath)}`,
    { method: 'POST', body: form },
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

/** Download a file from a VM directly to the browser/desktop. */
export async function downloadDirectFromVm(
  sliceName: string,
  nodeName: string,
  remotePath: string,
): Promise<void> {
  const url = `${BASE}/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/download-direct?remote_path=${encodeURIComponent(remotePath)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = remotePath.split('/').pop() || 'download';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

/** Download a folder from a VM as a zip file to the browser/desktop. */
export async function downloadFolderFromVm(
  sliceName: string,
  nodeName: string,
  remotePath: string,
): Promise<void> {
  const url = `${BASE}/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/download-folder?remote_path=${encodeURIComponent(remotePath)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const folderName = remotePath.split('/').pop() || 'folder';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${folderName}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

/** Create a directory on the VM. */
export function vmMkdir(sliceName: string, nodeName: string, path: string): Promise<{ created: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/mkdir`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

/** Delete a file or directory on the VM. */
export function vmDelete(sliceName: string, nodeName: string, path: string): Promise<{ deleted: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/delete`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

/** Execute an ad-hoc command on a VM node. */
export function executeOnVm(sliceName: string, nodeName: string, command: string): Promise<{ stdout: string; stderr: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/execute`, {
    method: 'POST',
    body: JSON.stringify({ command }),
  });
}

/** Read a text file from a VM for in-browser editing. */
export function readVmFileContent(sliceName: string, nodeName: string, path: string): Promise<{ path: string; content: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/read-content`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  });
}

/** Write a text file on a VM from in-browser editor. */
export function writeVmFileContent(sliceName: string, nodeName: string, path: string, content: string): Promise<{ path: string; status: string }> {
  return fetchJson(`/files/vm/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/write-content`, {
    method: 'POST',
    body: JSON.stringify({ path, content }),
  });
}

// --- Schedule / Calendar ---

export function getScheduleCalendar(days?: number): Promise<CalendarData> {
  const params = days !== undefined ? `?days=${days}` : '';
  return fetchJson(`/schedule/calendar${params}`);
}

export function findNextAvailable(params: { cores?: number; ram?: number; disk?: number; gpu?: string; site?: string }): Promise<NextAvailableResult> {
  const sp = new URLSearchParams();
  if (params.cores) sp.set('cores', String(params.cores));
  if (params.ram) sp.set('ram', String(params.ram));
  if (params.disk) sp.set('disk', String(params.disk));
  if (params.gpu) sp.set('gpu', params.gpu);
  if (params.site) sp.set('site', params.site);
  return fetchJson(`/schedule/next-available?${sp.toString()}`);
}

export function getAlternatives(params: { cores?: number; ram?: number; disk?: number; gpu?: string; preferred_site: string }): Promise<AlternativeResult> {
  const sp = new URLSearchParams();
  if (params.cores) sp.set('cores', String(params.cores));
  if (params.ram) sp.set('ram', String(params.ram));
  if (params.disk) sp.set('disk', String(params.disk));
  if (params.gpu) sp.set('gpu', params.gpu);
  sp.set('preferred_site', params.preferred_site);
  return fetchJson(`/schedule/alternatives?${sp.toString()}`);
}

// --- Reservations ---

export interface Reservation {
  id: string;
  slice_name: string;
  scheduled_time: string;
  duration_hours: number;
  auto_submit: boolean;
  status: 'pending' | 'active' | 'completed' | 'failed';
  created_at: string;
  error?: string | null;
}

export function listReservations(): Promise<Reservation[]> {
  return fetchJson('/schedule/reservations');
}

export function createReservation(data: { slice_name: string; scheduled_time: string; duration_hours?: number; auto_submit?: boolean }): Promise<Reservation> {
  return fetchJson('/schedule/reservations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
}

export function deleteReservation(id: string): Promise<void> {
  return fetchJson(`/schedule/reservations/${id}`, { method: 'DELETE' });
}

// --- Detailed Health Check ---

export interface DetailedHealthCheck {
  status: 'healthy' | 'degraded';
  uptime_seconds: number;
  version: string;
  checks: Record<string, { ok: boolean; message?: string; latency_ms?: number; port?: number; sites_configured?: number }>;
  slices: { active: number; total: number };
  memory_mb?: number;
  disk_free_gb?: number;
}

export function getDetailedHealth(): Promise<DetailedHealthCheck> {
  return fetchJson('/health/detailed');
}

// --- Provisioning ---

export function addProvision(rule: { source: string; slice_name: string; node_name: string; dest: string }): Promise<ProvisionRule> {
  return fetchJson('/files/provisions', {
    method: 'POST',
    body: JSON.stringify(rule),
  });
}

export function listProvisions(sliceName: string): Promise<ProvisionRule[]> {
  return fetchJson(`/files/provisions/${encodeURIComponent(sliceName)}`);
}

export function deleteProvision(sliceName: string, id: string): Promise<{ deleted: string }> {
  return fetchJson(`/files/provisions/${encodeURIComponent(sliceName)}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function executeProvisions(sliceName: string, nodeName?: string): Promise<Array<{ id: string; status: string; detail?: string }>> {
  const q = nodeName ? `?node_name=${encodeURIComponent(nodeName)}` : '';
  return fetchJson(`/files/provisions/${encodeURIComponent(sliceName)}/execute${q}`, { method: 'POST' });
}

// --- Boot Config ---

export function getBootConfig(sliceName: string, nodeName: string): Promise<BootConfig> {
  return fetchJson(`/files/boot-config/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}`);
}

export function saveBootConfig(sliceName: string, nodeName: string, config: BootConfig): Promise<BootConfig> {
  return fetchJson(`/files/boot-config/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}`, {
    method: 'PUT',
    body: JSON.stringify(config),
  });
}

export function executeBootConfig(sliceName: string, nodeName: string): Promise<BootExecResult[]> {
  return fetchJson(`/files/boot-config/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}/execute`, {
    method: 'POST',
  });
}

export function executeAllBootConfigs(sliceName: string): Promise<Record<string, BootExecResult[]>> {
  return fetchJson(`/files/boot-config/${encodeURIComponent(sliceName)}/execute-all`, {
    method: 'POST',
  });
}

export interface BootConfigStreamEvent {
  event: 'node' | 'step' | 'output' | 'error' | 'done';
  node?: string;
  type?: string;
  id?: string;
  message: string;
  status?: string;
}

export async function executeBootConfigStream(
  sliceName: string,
  onEvent: (evt: BootConfigStreamEvent) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/files/boot-config/${encodeURIComponent(sliceName)}/execute-all-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error('No response body');
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const evt = JSON.parse(line.slice(6)) as BootConfigStreamEvent;
          onEvent(evt);
        } catch { /* skip malformed */ }
      }
    }
  }
}

// --- Project Details (UIS API) ---

export function getProjectDetails(uuid: string): Promise<ProjectDetails> {
  return fetchJson(`/projects/${encodeURIComponent(uuid)}/details`);
}


// --- Projects (Core API) ---

let _userProjectsCache: Promise<{ projects: Array<{ name: string; uuid: string }>; active_project_id: string }> | null = null;

export function listUserProjects(): Promise<{ projects: Array<{ name: string; uuid: string }>; active_project_id: string }> {
  if (!_userProjectsCache) {
    _userProjectsCache = fetchJson('/projects');
    _userProjectsCache.catch(() => { _userProjectsCache = null; });
  }
  return _userProjectsCache;
}

export function switchProject(projectId: string): Promise<{ status: string; project_id: string; token_refreshed?: boolean; warning?: string; login_url?: string }> {
  return fetchJson('/projects/switch', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  });
}

export function saveConfig(config: {
  project_id: string;
  bastion_username: string;
  credmgr_host?: string;
  orchestrator_host?: string;
  core_api_host?: string;
  bastion_host?: string;
  am_host?: string;
  log_level?: string;
  log_file?: string;
  avoid?: string;
  ssh_command_line?: string;
  litellm_api_key?: string;
  nrp_api_key?: string;
}): Promise<{ status: string; configured: boolean }> {
  return fetchJson('/config/save', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

// -- Recipes ---------------------------------------------------------------

export function listRecipes(): Promise<RecipeSummary[]> {
  return fetchJson('/recipes');
}

export function toggleRecipeStar(name: string, starred: boolean): Promise<RecipeSummary> {
  return fetchJson(`/recipes/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify({ starred }),
  });
}

export function executeRecipe(name: string, sliceName: string, nodeName: string): Promise<RecipeExecResult> {
  return fetchJson(`/recipes/${encodeURIComponent(name)}/execute/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}`, {
    method: 'POST',
  });
}

export interface RecipeStreamEvent {
  event: 'step' | 'output' | 'error' | 'done';
  message?: string;
  status?: string;
  results?: Array<{ type: string; status: string; detail?: string }>;
}

export async function executeRecipeStream(
  name: string,
  sliceName: string,
  nodeName: string,
  onEvent: (evt: RecipeStreamEvent) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/recipes/${encodeURIComponent(name)}/execute/${encodeURIComponent(sliceName)}/${encodeURIComponent(nodeName)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  const reader = res.body?.getReader();
  if (!reader) throw new Error('No response body');
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const evt = JSON.parse(line.slice(6)) as RecipeStreamEvent;
          onEvent(evt);
        } catch { /* skip malformed */ }
      }
    }
  }
}

// -- Experiments -----------------------------------------------------------

export interface ExperimentSummary {
  name: string;
  description: string;
  author: string;
  tags: string[];
  dir_name: string;
  script_count: number;
  has_template: boolean;
  has_readme: boolean;
  is_experiment?: boolean;
  created?: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  readme: string;
  scripts: Array<{ filename: string }>;
  variables?: ExperimentVariable[];
}

export interface ExperimentTemplate {
  format: string;
  name: string;
  description: string;
  author: string;
  tags: string[];
  created: string;
  variables: ExperimentVariable[];
  fabric: { nodes: any[]; networks: any[]; facility_ports: any[]; port_mirrors: any[] };
  chameleon: { nodes: any[]; networks: any[]; floating_ips: string[] };
  cross_testbed: { connections: any[] };
  dir_name?: string;
  /** @deprecated use fabric/chameleon fields instead */
  testbeds?: string[];
}

export function listExperiments(): Promise<ExperimentSummary[]> {
  return fetchJson('/experiments');
}

export function getExperiment(name: string): Promise<ExperimentDetail> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}`);
}

export function createExperiment(body: { name: string; description?: string; author?: string; tags?: string[]; slice_name?: string }): Promise<ExperimentSummary> {
  return fetchJson('/experiments', { method: 'POST', body: JSON.stringify(body) });
}

export function deleteExperiment(name: string): Promise<{ status: string }> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function loadExperiment(name: string, sliceName?: string, variables?: Record<string, string>): Promise<SliceData> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/load`, {
    method: 'POST',
    body: JSON.stringify({ slice_name: sliceName || '', variables: variables || {} }),
  });
}

export function getExperimentTemplate(name: string): Promise<ExperimentTemplate> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/template`);
}

export function saveExperiment(data: {
  name: string;
  description: string;
  slice_name: string;
  variables?: ExperimentVariable[];
  author?: string;
  tags?: string[];
}): Promise<ExperimentTemplate> {
  return fetchJson('/experiments/save', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function getExperimentReadme(name: string): Promise<{ content: string }> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/readme`);
}

export function updateExperimentReadme(name: string, content: string): Promise<{ status: string }> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/readme`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export function getExperimentScript(name: string, filename: string): Promise<{ filename: string; content: string }> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/scripts/${encodeURIComponent(filename)}`);
}

export function saveExperimentScript(name: string, filename: string, content: string): Promise<{ status: string }> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/scripts/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export function deleteExperimentScript(name: string, filename: string): Promise<{ status: string }> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/scripts/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
  });
}

// -- Tunnels ---------------------------------------------------------------

export interface TunnelInfo {
  id: string;
  slice_name: string;
  node_name: string;
  remote_port: number;
  local_port: number;
  created_at: number;
  last_connection_at: number;
  status: string;
  error: string | null;
}

export function createTunnel(sliceName: string, nodeName: string, port: number): Promise<TunnelInfo> {
  return fetchJson('/tunnels', {
    method: 'POST',
    body: JSON.stringify({ slice_name: sliceName, node_name: nodeName, port }),
  });
}

export function listTunnels(): Promise<TunnelInfo[]> {
  return fetchJson('/tunnels');
}

export function closeTunnel(tunnelId: string): Promise<{ status: string; id: string }> {
  return fetchJson(`/tunnels/${encodeURIComponent(tunnelId)}`, { method: 'DELETE' });
}

// -- Storage ---------------------------------------------------------------

export function checkForUpdate(): Promise<UpdateInfo> {
  return fetchJson('/config/check-update');
}

export function rebuildStorage(): Promise<{
  status: string;
  directories: number;
  directories_created: number;
}> {
  return fetchJson('/config/rebuild-storage', { method: 'POST' });
}

// --- Unified Settings ---

export function getSettings(): Promise<LoomAISettings> {
  return fetchJson('/settings');
}

export function saveSettings(settings: LoomAISettings): Promise<LoomAISettings> {
  return fetchJson('/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  });
}

export function getToolConfigs(): Promise<ToolConfigStatus[]> {
  return fetchJson('/config/tool-configs');
}

export function resetToolConfig(tool: string): Promise<{ status: string }> {
  return fetchJson(`/config/tool-configs/${encodeURIComponent(tool)}/reset`, {
    method: 'POST',
  });
}

// Claude Code config management
export interface ClaudeConfigFile {
  name: string;
  content: string | null;
}

export interface ClaudeConfigStatus {
  files: ClaudeConfigFile[];
  logged_in: boolean;
  account_email: string | null;
}

export function getClaudeConfigFiles(): Promise<ClaudeConfigStatus> {
  return fetchJson('/config/claude-code/files');
}

export function updateClaudeConfigFile(filename: string, content: string): Promise<{ status: string }> {
  return fetchJson(`/config/claude-code/files/${encodeURIComponent(filename)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

export function triggerClaudeBackup(): Promise<{ status: string }> {
  return fetchJson('/config/claude-code/backup', { method: 'POST' });
}

// Folder browsing for AI tools
export interface FolderBrowseResult {
  path: string;
  parent: string | null;
  folders: string[];
  error?: string;
}

export function browseAiFolders(path?: string): Promise<FolderBrowseResult> {
  const params = path ? `?path=${encodeURIComponent(path)}` : '';
  return fetchJson(`/ai/browse-folders${params}`);
}

// --- Multi-User Management ---

export function listUsers(): Promise<UsersResponse> {
  return fetchJson('/users');
}

export function switchUser(uuid: string): Promise<{ status: string; active_user: string }> {
  return fetchJson('/users/switch', {
    method: 'POST',
    body: JSON.stringify({ uuid }),
  });
}

export function removeUser(uuid: string, deleteData: boolean = false): Promise<{ status: string; removed: string }> {
  const params = deleteData ? '?delete_data=true' : '';
  return fetchJson(`/users/${encodeURIComponent(uuid)}${params}`, { method: 'DELETE' });
}

export function migrateCurrentUser(): Promise<{ status: string; message: string; uuid?: string }> {
  return fetchJson('/users/migrate-current', { method: 'POST' });
}

// --- Settings Validation ---

export interface SettingTestResult {
  ok: boolean;
  message: string;
  latency_ms?: number;
  expires_at?: string;
  model_count?: number;
  project_name?: string;
}

export function testSetting(settingName: string): Promise<SettingTestResult> {
  return fetchJson(`/settings/test/${settingName}`, { method: 'POST' });
}

export function testAllSettings(): Promise<Record<string, SettingTestResult>> {
  return fetchJson('/settings/test-all', { method: 'POST' });
}
