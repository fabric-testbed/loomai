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
  subnet_details?: Array<{ id: string; cidr: string; name: string }>;
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
  type: 'instance' | 'lease' | 'network' | 'floating_ip';
  id: string;
  name: string;
  site: string;
  node_type?: string;
  image?: string;
  lease_id?: string;
  cidr?: string;
  status?: string;
  floating_ip?: string;
  ssh_ready?: boolean;
}

export interface ChameleonSlice {
  id: string;
  name: string;
  state: string;  // "Draft" | "Deploying" | "Active" | "Error" | "Terminated"
  created: string;
  site?: string;  // Legacy single-site field
  // Design fields (from drafts):
  nodes: ChameleonDraftNode[];
  networks: ChameleonDraftNetwork[];
  floating_ips: Array<string | { node_id: string; nic: number }>;
  // Deployed resources:
  resources: ChameleonSliceResource[];
}

// Keep alias for imports that still reference ChameleonDraft
export type ChameleonDraft = ChameleonSlice;
