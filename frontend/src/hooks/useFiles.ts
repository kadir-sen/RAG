import { useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listFiles, uploadFile as apiUploadFile, deleteFile } from '../api/fileApi';

export interface UploadingFile {
  name: string;
  progress: number; // 0-100
  status: 'uploading' | 'completed' | 'error';
  error?: string;
}

export function useFiles() {
  const queryClient = useQueryClient();
  const [uploading, setUploading] = useState<UploadingFile[]>([]);

  const query = useQuery({
    queryKey: ['files'],
    queryFn: listFiles,
    staleTime: 5_000,
    refetchInterval: uploading.some((u) => u.status === 'uploading') ? 3_000 : false,
  });

  const uploadMultiple = useCallback(async (files: File[]) => {
    // Initialize all files as uploading
    const initial: UploadingFile[] = files.map((f) => ({
      name: f.name,
      progress: 0,
      status: 'uploading',
    }));
    setUploading(initial);

    // Upload with concurrency limit (3 at a time)
    const CONCURRENCY = 3;
    const results = [...initial];

    const updateFile = (index: number, patch: Partial<UploadingFile>) => {
      results[index] = { ...results[index], ...patch };
      setUploading([...results]);
    };

    const uploadOne = async (file: File, index: number) => {
      try {
        await apiUploadFile(file, (pct) => {
          updateFile(index, { progress: pct });
        });
        updateFile(index, { progress: 100, status: 'completed' });
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed';
        updateFile(index, { status: 'error', error: msg });
      }
    };

    // Process in batches of CONCURRENCY
    for (let i = 0; i < files.length; i += CONCURRENCY) {
      const batch = files.slice(i, i + CONCURRENCY);
      await Promise.all(
        batch.map((file, j) => uploadOne(file, i + j)),
      );
      // Refresh file list after each batch
      queryClient.invalidateQueries({ queryKey: ['files'] });
    }

    queryClient.invalidateQueries({ queryKey: ['files'] });
    queryClient.invalidateQueries({ queryKey: ['library'] });

    // Clear upload status after 3 seconds
    setTimeout(() => setUploading([]), 3000);
  }, [queryClient]);

  const remove = useMutation({
    mutationFn: deleteFile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files'] });
      queryClient.invalidateQueries({ queryKey: ['library'] });
    },
  });

  return {
    files: query.data ?? [],
    isLoading: query.isLoading,
    uploadMultiple,
    uploading,
    isUploading: uploading.some((u) => u.status === 'uploading'),
    deleteFile: remove.mutate,
  };
}
