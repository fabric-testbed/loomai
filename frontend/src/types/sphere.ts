// SPHERE / MergeTB types — mirrors the backend routes/sphere.py responses.

export interface SphereStatus {
  enabled: boolean;
  configured: boolean;
  grpc_endpoint: string;
  default_project: string;
}

// A realization summary or full realization (both carry id/eid/pid).
export interface SphereRealization {
  id: string;       // realization name (rname)
  eid: string;      // experiment
  pid: string;      // project
  complete?: boolean;
  state?: 'complete' | 'failed' | 'pending';
  error?: string;
  xhash?: string;
  creator?: string;
  // full realizations also carry nodes/links; kept loose on purpose.
  [key: string]: any;
}

export interface SphereGraph {
  nodes: any[];
  edges: any[];
}

// An XDC (Experiment Data Conduit) — a Merge-hosted jump container that, once
// attached to a materialization, is the path to SSH into experiment nodes.
export interface SphereXdc {
  name: string;
  fqdn?: string;
  creator?: string;
  type?: string;            // "shared" | "personal"
  materialization?: string; // attached realization ref, if any
  status?: string;          // task HighestStatus (when requested)
  ready?: boolean | null;   // true when status == "Success"
  [key: string]: any;
}
