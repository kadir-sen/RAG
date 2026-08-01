export interface ProjectStats {
  files: { document: number; email: number; data: number };
  total_files: number;
  queued: number;
  processing: number;
  ready: number;
  failed: number;
  eta_seconds: number | null;
  calibration_size: number;
  calibration_complete: boolean;
  report_ready: boolean;
}

export interface Project {
  project_id: string;
  name: string;
  slug: string;
  embedding_profile: 'local-bge-v1' | 'gemini-embedding-2';
  role: 'owner' | 'editor' | 'viewer' | 'admin';
  archived_at: string | null;
  stats: ProjectStats;
}
