import { useQuery } from '@tanstack/react-query';
import { getDocContent } from '../api/fileApi';
import { useUIStore, type ViewerDoc } from '../stores/uiStore';

export function useDocViewer() {
  const { rightPanelOpen, rightPanelDoc, openDocument, closeViewer } =
    useUIStore();

  const hasValidDocId = !!rightPanelDoc?.docId && rightPanelDoc.docId.trim().length > 0;

  const contentQuery = useQuery({
    queryKey: ['docContent', rightPanelDoc?.docId, rightPanelDoc?.anchor],
    queryFn: () =>
      getDocContent(rightPanelDoc!.docId, rightPanelDoc?.anchor ?? ''),
    enabled: rightPanelOpen && hasValidDocId,
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
