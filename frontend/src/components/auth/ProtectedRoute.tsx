import { useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';

interface Props {
  children: React.ReactNode;
}

export default function ProtectedRoute({ children }: Props) {
  const token = useAuthStore((s) => s.token);
  const refreshMe = useAuthStore((s) => s.refreshMe);
  const location = useLocation();

  useEffect(() => {
    if (token) {
      void refreshMe();
    }
  }, [token, refreshMe]);

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
