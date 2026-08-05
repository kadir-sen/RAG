export interface ProjectStats {
  files: { document: number; email: number; data: number; programme: number };
  total_files: number;
  queued: number;
  processing: number;
  ready: number;
  failed: number;
  eta_seconds: number | null;
  calibration_size: number;
  calibration_complete: boolean;
  report_ready: boolean;
  vector: {
    status: 'empty' | 'provisioning' | 'provisioned' | 'indexing' | 'ready' | 'error' | 'archived';
    point_count: number;
    embedding_profile: 'local-bge-v1' | 'gemini-embedding-2';
    last_error: string | null;
  };
}

export interface Project {
  project_id: string;
  name: string;
  slug: string;
  embedding_profile: 'local-bge-v1' | 'gemini-embedding-2';
  role: 'owner' | 'editor' | 'viewer' | 'admin';
  archived_at: string | null;
  stats: ProjectStats;
  usage: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    credits_used: number;
    estimated_provider_cost_usd?: number;
    uncovered_credits?: number;
  };
}
