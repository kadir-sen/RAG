import { Navigate, useLocation } from 'react-router-dom';
import { useProjectStore } from '../../stores/projectStore';

export default function ProjectRequired({ children }: { children: React.ReactNode }) {
  const projectId = useProjectStore((s) => s.selectedProjectId);
  const location = useLocation();
  if (!projectId) {
    return <Navigate to="/projects" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}
