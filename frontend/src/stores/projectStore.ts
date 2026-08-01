import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Project } from '../types/projects';
import { listProjects } from '../api/projectApi';
import { useChatStore } from './chatStore';
import { useUIStore } from './uiStore';

interface ProjectState {
  projects: Project[];
  selectedProjectId: string | null;
  loading: boolean;
  load: () => Promise<void>;
  select: (projectId: string | null) => void;
  clear: () => void;
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set, get) => ({
      projects: [],
      selectedProjectId: null,
      loading: false,
      async load() {
        set({ loading: true });
        try {
          const projects = await listProjects();
          const selected = get().selectedProjectId;
          set({
            projects,
            selectedProjectId: selected && projects.some((p) => p.project_id === selected)
              ? selected
              : null,
          });
        } finally {
          set({ loading: false });
        }
      },
      select(projectId) {
        if (get().selectedProjectId !== projectId) {
          // Project changes are hard workspace boundaries. Clear client-only
          // state immediately so a conversation, selected document, or open
          // viewer from the previous project can never flash in the next one.
          useChatStore.getState().setConversation('');
          useUIStore.getState().closeViewer();
        }
        set({ selectedProjectId: projectId });
      },
      clear() { set({ projects: [], selectedProjectId: null }); },
    }),
    {
      name: 'coair-project',
      partialize: (state) => ({ selectedProjectId: state.selectedProjectId }),
    },
  ),
);
