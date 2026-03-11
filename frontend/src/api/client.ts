/** API client for the FABRIC Web GUI backend. */

import type { SliceSummary, SliceData, SiteInfo, SiteDetail, LinkInfo, ComponentModel, ConfigStatus, ProjectsResponse, ValidationResult, SiteMetrics, LinkMetrics, FileEntry, ProvisionRule, BootConfig, BootExecResult, SliceKeySet, VMTemplateSummary, VMTemplateDetail, VMTemplateVariantDetail, HostInfo, ProjectDetails, ToolFile, RecipeSummary, RecipeExecResult, UpdateInfo, IpHint, L3Config, FacilityPortInfo, LoomAISettings, ToolConfigStatus } from '../types/fabric';

const BASE = '/api';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
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

export function listSlices(): Promise<SliceSummary[]> {
  return fetchJson('/slices');
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
  source_slice: string;
  created: string;
  node_count: number;
  network_count: number;
  dir_name: string;
  has_template?: boolean;
  has_deploy?: boolean;
  has_run?: boolean;
  deploy_args?: ScriptArg[];
  run_args?: ScriptArg[];
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

export function resyncTemplates(): Promise<TemplateSummary[]> {
  return fetchJson('/templates/resync', { method: 'POST' });
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
  script: 'deploy.sh' | 'run.sh',
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
  script: 'deploy.sh' | 'run.sh',
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

export function resyncVmTemplates(): Promise<VMTemplateSummary[]> {
  return fetchJson('/vm-templates/resync', { method: 'POST' });
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

export function listSites(): Promise<SiteInfo[]> {
  return fetchJson('/sites');
}

export function listLinks(): Promise<LinkInfo[]> {
  return fetchJson('/links');
}

export function listFacilityPorts(): Promise<FacilityPortInfo[]> {
  return fetchJson('/facility-ports');
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

export function getAiModels(): Promise<{ models: string[]; default: string; error?: string }> {
  return fetchJson('/ai/models');
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
}): Promise<{
  status: string;
  uuid: string;
  title: string;
  visibility: string;
  version: string;
}> {
  return fetchJson('/artifacts/publish', {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export function listValidTags(): Promise<{ tags: ValidTag[] }> {
  return fetchJson('/artifacts/valid-tags');
}

// --- My Artifacts (annotated local + authorship) ---

export interface LocalArtifact {
  name: string;
  description: string;
  source: string;
  artifact_uuid?: string;
  created: string;
  tags: string[];
  dir_name: string;
  category: string;
  is_from_marketplace: boolean;
  node_count?: number;
  network_count?: number;
  remote_status?: 'linked' | 'not_linked' | 'remote_deleted';
  is_author?: boolean;
  remote_artifact?: RemoteArtifact | null;
}

export interface MyArtifactsResponse {
  local_artifacts: LocalArtifact[];
  authored_remote_only: RemoteArtifact[];
  user_email: string;
}

export function getMyArtifacts(): Promise<MyArtifactsResponse> {
  return fetchJson('/artifacts/my');
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
  return fetchJson('/config/login');
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

export function listUserProjects(): Promise<{ projects: Array<{ name: string; uuid: string }>; active_project_id: string }> {
  return fetchJson('/projects');
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
  created?: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  readme: string;
  scripts: Array<{ filename: string }>;
  node_count?: number;
  network_count?: number;
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

export function loadExperiment(name: string, sliceName?: string): Promise<SliceData> {
  return fetchJson(`/experiments/${encodeURIComponent(name)}/load`, {
    method: 'POST',
    body: JSON.stringify({ slice_name: sliceName || '' }),
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
  slice_templates_reseeded: number;
  vm_templates_reseeded: number;
  slice_templates_total: number;
  vm_templates_total: number;
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
