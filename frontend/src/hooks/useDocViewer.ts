import { useQuery } from '@tanstack/react-query';
import { getDocContent } from '../api/fileApi';
import { useUIStore, type ViewerDoc } from '../stores/uiStore';

export function useDocViewer() {
  const { rightPanelOpen, rightPanelDoc, openDocument, closeViewer } =
    useUIStore();

  const contentQuery = useQuery({
    queryKey: ['docContent', rightPanelDoc?.docId, rightPanelDoc?.anchor],
    queryFn: () =>
      getDocContent(rightPanelDoc!.docId, rightPanelDoc?.anchor ?? ''),
    enabled: rightPanelOpen && !!rightPanelDoc,
    staleTime: Infinity,
  });

  return {
    isOpen: rightPanelOpen,
    doc: rightPanelDoc,
    content: contentQuery.data,
    isLoadingContent: contentQuery.isLoading,
    openDocument: (doc: ViewerDoc) => openDocument(doc),
    closeViewer,
  };
}
