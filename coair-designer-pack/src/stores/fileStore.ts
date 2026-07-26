import { create } from 'zustand';
import type { FileInfo } from '../types/api';

interface FileState {
  files: FileInfo[];
  setFiles: (files: FileInfo[]) => void;
  isUploading: boolean;
  setUploading: (v: boolean) => void;
}

export const useFileStore = create<FileState>((set) => ({
  files: [],
  setFiles: (files) => set({ files }),
  isUploading: false,
  setUploading: (v) => set({ isUploading: v }),
}));
