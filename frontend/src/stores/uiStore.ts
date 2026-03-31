import { create } from 'zustand';

export interface ViewerDoc {
  docId: string;
  fileName: string;
  anchor?: string;
  highlightText?: string;
}

interface UIState {
  sidebarOpen: boolean;
  leftDrawerOpen: boolean;
  rightPanelOpen: boolean;
  rightPanelDoc: ViewerDoc | null;
  settingsOpen: boolean;
  leftDrawerTab: 'documents' | 'library';
  toggleSidebar: () => void;
  toggleLeftDrawer: () => void;
  openDocument: (doc: ViewerDoc) => void;
  closeViewer: () => void;
  toggleSettings: () => void;
  setLeftDrawerTab: (tab: 'documents' | 'library') => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  leftDrawerOpen: true,
  rightPanelOpen: false,
  rightPanelDoc: null,
  settingsOpen: false,
  leftDrawerTab: 'documents',

  toggleSidebar: () =>
    set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  toggleLeftDrawer: () =>
    set((s) => ({ leftDrawerOpen: !s.leftDrawerOpen })),

  openDocument: (doc) =>
    set({ rightPanelOpen: true, rightPanelDoc: doc }),

  closeViewer: () =>
    set({ rightPanelOpen: false, rightPanelDoc: null }),

  toggleSettings: () =>
    set((s) => ({ settingsOpen: !s.settingsOpen })),

  setLeftDrawerTab: (tab) =>
    set({ leftDrawerTab: tab }),
}));
