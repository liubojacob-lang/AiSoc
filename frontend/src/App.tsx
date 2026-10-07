import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "@/components/Layout";
import { Spinner, ToastHost } from "@/components/ui";
import { useAuth } from "@/stores/auth";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Alerts from "@/pages/Alerts";
import Incidents from "@/pages/Incidents";
import Knowledge from "@/pages/Knowledge";
import Admin from "@/pages/Admin";
import Approvals from "@/pages/Approvals";
import Assistant from "@/pages/Assistant";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner className="h-8 w-8 text-sky-400" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  const loadMe = useAuth((s) => s.loadMe);
  useEffect(() => {
    loadMe();
  }, [loadMe]);

  return (
    <>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Protected><Layout /></Protected>}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/incidents" element={<Incidents />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/assistant" element={<Assistant />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/admin" element={<Admin />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ToastHost />
    </>
  );
}
