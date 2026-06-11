/** Chameleon Cloud types matching backend response shapes. */

export interface ChameleonSite {
  name: string;              // "CHI@TACC"
  auth_url: string;
  configured: boolean;
  location: {
    lat: number;
    lon: number;
    city?: string;
  };
}

export interface ChameleonNodeType {
  name: string;              // "compute_haswell"
  architecture?: string;
  cpu_count?: number;
  ram_mb?: number;
  disk_gb?: number;
  gpu?: string;
  total?: number;
  available?: number;
}

export interface ChameleonLease {
  id: string;
  name: string;
  _site: string;
  status: string;            // "ACTIVE", "PENDING", "TERMINATED", "ERROR"
  start_date: string;
  end_date: string;
  project_id?: string;
  reservations: ChameleonReservation[];
}

export interface ChameleonReservation {
  id: string;
  resource_type?: string;
  status?: string;
  min?: number;
  max?: number;
}

export interface ChameleonInstance {
  id: string;
  name: string;
  site: string;
  status: string;            // "ACTIVE", "BUILD", "SHUTOFF", "ERROR"
  image: string;
  ip_addresses: string[];
  floating_ip?: string;
  created?: string;
}

export interface ChameleonImage {
  id: string;
  name: string;
  status?: string;
  size_mb?: number;
  created?: string;
  architecture?: string;
}

export interface ChameleonStatus {
  enabled: boolean;
  configured: boolean;
  sites: Record<string, { configured: boolean }>;
}

export interface ChameleonTestResult {
  ok: boolean;
  error: string;
  latency_ms: number;
}

export interface ChameleonNetwork {
  id: string;
  name: string;
  site: string;
  status?: string;
  shared?: boolean;
  vlan?: number | null;
  physical_network?: string;
  subnet_details?: Array<{ id: string; cidr: string; name: string }>;
}

export interface ChameleonFacilityPortInterface {
  name: string;
  vlan_range: Array<string | number>;
  local_name?: string;
  device_name?: string;
  allocated_vlans?: Array<string | number>;
  region?: string;
}

export interface ChameleonFacilityPort {
  name: string;
  site: string;
  fabric_site?: string;
  chameleon_site?: string;
  interfaces: ChameleonFacilityPortInterface[];
}

export interface ChameleonFacilityPortList {
  chameleon_site: string;
  fabric_site: string;
  facility_ports: ChameleonFacilityPort[];
  vlans: number[];
  suggested_vlan?: number | null;
}

export interface ChameleonNodeTypeDetail {
  node_type: string;
  total: number;
  reservable: number;
  cpu_arch?: string;
  cpu_count?: number;
  cpu_model?: string;
  ram_gb?: number;
  disk_gb?: number;
  gpu?: string | null;
  gpu_count?: number;
}

export interface ChameleonDraftNode {
  id: string;
  name: string;
  node_type: string;
  image: string;
  count: number;
  site: string;
  key_name?: string;
  status?: string;
  instance_id?: string;
  floating_ip?: string;
  management_ip?: string;
  ssh_command?: string;
  ssh_user?: string;
  ip_addresses?: string[];
  port_id?: string;
  lease_id?: string;
  reservation_id?: string;
  network?: { id: string; name: string } | null;
  interfaces?: Array<{ nic: number; network: { id: string; name: string } | null }>;
}

export interface ChameleonDraftNetwork {
  id: string;
  name: string;
  connected_nodes: string[];
}

// ChameleonDraft is now an alias for ChameleonSlice (unified type below)

export interface ChameleonDeployLeaseResult {
  site: string;
  lease_id: string;
  lease_name: string;
  status: string;
  reservations: ChameleonReservation[];
}

export interface ChameleonDeployResult {
  draft_id: string;
  leases: ChameleonDeployLeaseResult[];
  errors?: string[];
}

export interface ChameleonSliceResource {
  resource_id: string;
  provider?: 'chameleon' | string;
  type: 'instance' | 'lease' | 'network' | 'floating_ip' | 'security_group';
  resource_type?: string;
  type_label?: string;
  id: string;
  provider_id?: string;
  name: string;
  site: string;
  ownership?: 'managed' | 'imported';
  managed?: boolean;
  created_by?: 'loomai' | 'external' | string;
  delete_with_slice?: boolean;
  attached_at?: string;
  relationship?: Record<string, string>;
  node_type?: string;
  image?: string;
  lease_id?: string;
  reservations?: ChameleonReservation[];
  start_date?: string;
  end_date?: string;
  cidr?: string;
  status?: string;
  ip_addresses?: string[];
  floating_ip?: string;
  floating_ip_id?: string;
  management_ip?: string;
  ssh_command?: string;
  ssh_user?: string;
  port_id?: string;
  fixed_ip?: string;
  ssh_ready?: boolean;
  planned_node_id?: string;
  planned_node_name?: string;
  key_name?: string;
}

export interface ChameleonSlice {
  id: string;
  name: string;
  provider?: 'chameleon';
  state: string;  // "Draft" | "Deploying" | "Active" | "Error" | "Terminated"
  created: string;
  site?: string;  // Legacy single-site field
  sites?: string[];
  // Design fields (from drafts):
  nodes: ChameleonDraftNode[];
  networks: ChameleonDraftNetwork[];
  floating_ips: Array<string | { node_id: string; nic: number }>;
  // Deployed resources:
  resources: ChameleonSliceResource[];
}

// Keep alias for imports that still reference ChameleonDraft
export type ChameleonDraft = ChameleonSlice;
