/** Types matching the backend API response shapes. */

export interface SliceSummary {
  name: string;
  id: string;
  state: string;
  archived?: boolean;
  has_errors?: boolean;
}

export interface SliceInterface {
  name: string;
  node_name: string;
  network_name: string;
  vlan: string;
  mac: string;
  ip_addr: string;
  bandwidth: string;
  mode: string;
}

export interface SliceComponent {
  name: string;
  model: string;
  type: string;
  interfaces: SliceInterface[];
}

export interface SliceNode {
  name: string;
  site: string;
  site_group?: string;
  host: string;
  cores: number;
  ram: number;
  disk: number;
  image: string;
  image_type: string;
  management_ip: string;
  reservation_state: string;
  error_message: string;
  username: string;
  components: SliceComponent[];
  interfaces: SliceInterface[];
}

export interface IpHint {
  last_octet?: number;
  last_octet_range?: string;
}

export interface L3Config {
  mode: 'auto' | 'manual' | 'user_octet';
  route_mode: 'default_fabnet' | 'custom';
  custom_routes: string[];
  default_fabnet_subnet: string;
}

export interface SliceNetwork {
  name: string;
  type: string;
  layer: string;
  subnet: string;
  gateway: string;
  interfaces: SliceInterface[];
  ip_hints?: Record<string, IpHint>;
  l3_config?: L3Config;
}

export interface CyNode {
  data: Record<string, string>;
  classes: string;
}

export interface CyEdge {
  data: Record<string, string>;
  classes: string;
}

export interface CyGraph {
  nodes: CyNode[];
  edges: CyEdge[];
}

export interface SliceFacilityPort {
  name: string;
  site: string;
  vlan: string;
  bandwidth: string;
  interfaces: SliceInterface[];
}

export interface SliceErrorMessage {
  sliver: string;
  message: string;
}

export interface SlicePortMirror {
  name: string;
  mirror_interface_name: string;
  receive_interface_name: string;
  mirror_direction: string;
}

export interface SliceData {
  name: string;
  id: string;
  state: string;
  dirty: boolean;
  lease_start: string;
  lease_end: string;
  error_messages: SliceErrorMessage[];
  nodes: SliceNode[];
  networks: SliceNetwork[];
  facility_ports: SliceFacilityPort[];
  port_mirrors: SlicePortMirror[];
  graph: CyGraph;
}

export interface SiteInfo {
  name: string;
  lat: number;
  lon: number;
  state: string;
  hosts: number;
  cores_available: number;
  cores_capacity: number;
  ram_available: number;
  ram_capacity: number;
  disk_available: number;
  disk_capacity: number;
}

export interface ComponentModel {
  model: string;
  type: string;
  description: string;
}

export interface HostInfo {
  name: string;
  cores_available: number;
  cores_capacity: number;
  ram_available: number;
  ram_capacity: number;
  disk_available: number;
  disk_capacity: number;
  components: Record<string, { available: number; capacity: number }>;
}

export interface LinkInfo {
  site_a: string;
  site_b: string;
}

export interface ComponentResource {
  available: number;
  allocated: number;
  capacity: number;
}

export interface SiteDetail extends SiteInfo {
  cores_allocated: number;
  ram_allocated: number;
  disk_allocated: number;
  components: Record<string, ComponentResource>;
}

export interface PrometheusResult {
  metric: Record<string, string>;
  value: [number, string];
}

export interface SiteMetrics {
  site: string;
  node_load1: PrometheusResult[];
  node_load5: PrometheusResult[];
  node_load15: PrometheusResult[];
  dataplaneInBits: PrometheusResult[];
  dataplaneOutBits: PrometheusResult[];
}

export interface LinkMetrics {
  site_a: string;
  site_b: string;
  a_to_b_in: PrometheusResult[];
  a_to_b_out: PrometheusResult[];
  b_to_a_in: PrometheusResult[];
  b_to_a_out: PrometheusResult[];
}

export interface ValidationIssue {
  severity: 'error' | 'warning';
  message: string;
  remedy: string;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
}

export interface SliceKeySet {
  name: string;
  is_default: boolean;
  fingerprint: string;
  pub_key: string;
}

export interface ConfigStatus {
  configured: boolean;
  has_token: boolean;
  has_bastion_key: boolean;
  has_slice_key: boolean;
  token_info: {
    email?: string;
    name?: string;
    uuid?: string;
    exp?: number;
    projects?: ProjectInfo[];
    error?: string;
  } | null;
  project_id: string;
  bastion_username: string;
  bastion_pub_key?: string;
  bastion_key_fingerprint?: string;
  slice_pub_key?: string;
  slice_key_fingerprint?: string;
  default_slice_key?: string;
  slice_key_sets?: string[];
  ai_api_key_set?: boolean;
  nrp_api_key_set?: boolean;
}

export interface ProjectInfo {
  uuid: string;
  name: string;
}

export interface ProjectsResponse {
  projects: ProjectInfo[];
  bastion_login: string;
  email: string;
  name: string;
}

export interface FileEntry {
  name: string;
  type: 'file' | 'dir';
  size: number;
  modified: string;
}

export interface ProvisionRule {
  id: string;
  source: string;
  slice_name: string;
  node_name: string;
  dest: string;
}

export interface BootUpload {
  id: string;
  source: string;   // path relative to container storage
  dest: string;      // absolute path on VM
}

export interface BootCommand {
  id: string;
  command: string;
  order: number;
}

export interface BootNetConfig {
  id: string;
  iface: string;
  mode: 'auto' | 'manual';
  ip?: string;
  subnet?: string;
  gateway?: string;
  order: number;
}

export interface BootConfig {
  uploads: BootUpload[];
  commands: BootCommand[];
  network: BootNetConfig[];
}

export interface ToolFile {
  filename: string;
  content?: string;
}

export interface VMTemplateVariant {
  label: string;
  dir: string;
}

export interface VMTemplateSummary {
  name: string;
  description: string;
  image: string;
  created: string;
  dir_name: string;
  images: string[];
  variant_count: number;
  version: string;
}

export interface VMTemplateDetail extends VMTemplateSummary {
  boot_config?: BootConfig;
  variants?: Record<string, VMTemplateVariant>;
  setup_script?: string;
  remote_dir?: string;
  tools?: ToolFile[];
  cores?: number;
  ram?: number;
  disk?: number;
  site?: string;
  host?: string;
  image_type?: string;
  username?: string;
  instance_type?: string;
  components?: Array<{ name: string; model: string }>;
}

export interface VMTemplateVariantDetail {
  image: string;
  label: string;
  boot_config: BootConfig;
  template_name: string;
  variant_dir: string;
  remote_dir: string;
}

export interface BootExecResult {
  type: 'upload' | 'command' | 'network';
  id: string;
  status: 'ok' | 'error';
  detail?: string;
}

export interface BootConfigStreamEvent {
  event: 'node' | 'step' | 'output' | 'error' | 'done';
  node?: string;
  type?: string;
  id?: string;
  message: string;
  status?: string;
}

export interface ProjectPerson {
  name: string;
  email: string;
  uuid: string;
}

export interface ProjectFunding {
  agency: string;
  award_number: string;
  award_amount: number;
  directorate: string;
}

export interface ProjectDetails {
  uuid: string;
  name: string;
  description: string;
  project_type: string;
  active: boolean;
  created: string;
  communities: string[];
  tags: string[];
  project_lead: ProjectPerson | null;
  project_owners: ProjectPerson[];
  project_members: ProjectPerson[];
  project_creators: ProjectPerson[];
  project_funding: ProjectFunding[];
  slice_counts: {
    active: number;
    total: number;
  };
}

// -- Recipe types -----------------------------------------------------------

export interface RecipeSummary {
  name: string;
  description: string;
  image_patterns: Record<string, string>;
  dir_name: string;
  starred: boolean;
}

export interface RecipeExecResult {
  recipe: string;
  node: string;
  results: Array<{ type: string; status: 'ok' | 'error'; detail?: string }>;
  status: 'ok' | 'partial' | 'error';
}

export interface UpdateInfo {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  docker_hub_url: string;
  published_at: string | null;
}

export interface FacilityPortInterface {
  name: string;
  vlan_range: string[];
  local_name: string;
  device_name: string;
  allocated_vlans: string[];
  region: string;
}

export interface FacilityPortInfo {
  name: string;
  site: string;
  interfaces: FacilityPortInterface[];
}

// -- LoomAI Settings --------------------------------------------------------

export interface LoomAISettings {
  schema_version: number;
  paths: {
    storage_dir: string;
    config_dir: string;
    artifacts_dir: string;
    slices_dir: string;
    notebooks_dir: string;
    ai_tools_dir: string;
    token_file: string;
    bastion_key_file: string;
    slice_keys_dir: string;
    ssh_config_file: string;
    log_file: string;
  };
  fabric: {
    project_id: string;
    bastion_username: string;
    hosts: {
      credmgr: string;
      orchestrator: string;
      core_api: string;
      bastion: string;
      artifact_manager: string;
    };
    logging: { level: string };
    avoid_sites: string[];
    ssh_command_line: string;
  };
  ai: {
    fabric_api_key: string;
    nrp_api_key: string;
    ai_server_url: string;
    nrp_server_url: string;
    tools: Record<string, boolean>;
  };
  services: {
    jupyter_port: number;
    model_proxy_port: number;
  };
  tool_configs: Record<string, object>;
}

export interface ToolConfigStatus {
  tool: string;
  has_config: boolean;
  files: string[];
}

export interface UserInfo {
  uuid: string;
  name: string;
  email: string;
  is_active: boolean;
  added_at: string;
}

export interface UsersResponse {
  active_user: string | null;
  users: UserInfo[];
}
