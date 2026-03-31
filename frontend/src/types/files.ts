export interface WorkspaceFile {
  id: string;
  name: string;
  fileType: string;
  pages?: number;
  ocrPages: number;
  tables: number;
  rows: number;
}

export interface UploadItem {
  file: File;
  progress: number;
  status: 'pending' | 'uploading' | 'done' | 'error';
  error?: string;
}
