import apiClient from './client';
import type { Project } from '../types/projects';

export async function listProjects(): Promise<Project[]> {
  const { data } = await apiClient.get<{ projects: Project[] }>('/projects');
  return data.projects;
}

export async function createProject(
  name: string,
  embeddingProfile: 'local-bge-v1' | 'gemini-embedding-2' = 'local-bge-v1',
): Promise<Project> {
  const { data } = await apiClient.post<Project>('/projects', {
    name,
    embedding_profile: embeddingProfile,
  });
  return data;
}

export async function archiveProject(projectId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}`);
}

export async function renameProject(projectId: string, name: string): Promise<Project> {
  const { data } = await apiClient.patch<Project>(`/projects/${projectId}`, { name });
  return data;
}
