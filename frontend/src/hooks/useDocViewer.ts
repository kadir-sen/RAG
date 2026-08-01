import { useQuery } from '@tanstack/react-query';
import { getDocContent } from '../api/fileApi';
import { useUIStore, type ViewerDoc } from '../stores/uiStore';
import { useProjectStore } from '../stores/projectStore';

export function useDocViewer() {
  const { rightPanelOpen, rightPanelDoc, openDocument, closeViewer } =
    useUIStore();
  const projectId = useProjectStore((state) => state.selectedProjectId);

  // Either identifier is enough. A citation stored before a re-ingest carries a
  // doc_id that no longer resolves, and the file name is what rescues it.
  const canFetch =
    !!rightPanelDoc?.docId?.trim() || !!rightPanelDoc?.fileName?.trim();

  const contentQuery = useQuery({
    queryKey: [
      'docContent', projectId, rightPanelDoc?.docId, rightPanelDoc?.anchor,
      rightPanelDoc?.fileName,
    ],
    queryFn: () =>
      getDocContent(
        rightPanelDoc!.docId,
        rightPanelDoc?.anchor ?? '',
        rightPanelDoc?.fileName ?? '',
      ),
    enabled: rightPanelOpen && canFetch,
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
