import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router";
import { getAdminToken } from "./lib/adminHttp";
import ActivationPage from "./pages/ActivationPage";
import CostAuditPage from "./pages/CostAuditPage";
import LoginPage from "./pages/LoginPage";
import ImSafetyPage from "./pages/ImSafetyPage";
import OverviewPage from "./pages/OverviewPage";
import PlansPage from "./pages/PlansPage";
import PriceVersionsPage from "./pages/PriceVersionsPage";
import ProvidersPage from "./pages/ProvidersPage";
import TasksPage from "./pages/TasksPage";
import UsersPage from "./pages/UsersPage";
import Shell from "./shell/Shell";

function RequireAdmin({ children }: { children: ReactElement }) {
  if (!getAdminToken()) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAdmin>
            <Shell />
          </RequireAdmin>
        }
      >
        <Route path="/" element={<OverviewPage />} />
        <Route path="/plans" element={<PlansPage />} />
        <Route path="/prices" element={<PriceVersionsPage />} />
        <Route path="/activation" element={<ActivationPage />} />
        <Route path="/providers" element={<ProvidersPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/cost-audit" element={<CostAuditPage />} />
        <Route path="/im-safety" element={<ImSafetyPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
