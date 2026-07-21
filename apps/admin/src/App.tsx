import { Navigate, Route, Routes } from "react-router-dom";
import { getAdminToken } from "./lib/adminHttp";
import ActivationPage from "./pages/ActivationPage";
import CostAuditPage from "./pages/CostAuditPage";
import LoginPage from "./pages/LoginPage";
import OverviewPage from "./pages/OverviewPage";
import PlansPage from "./pages/PlansPage";
import PriceVersionsPage from "./pages/PriceVersionsPage";
import ProvidersPage from "./pages/ProvidersPage";
import UsersPage from "./pages/UsersPage";
import Shell from "./shell/Shell";

function RequireAdmin({ children }: { children: JSX.Element }) {
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
        <Route path="/users" element={<UsersPage />} />
        <Route path="/cost-audit" element={<CostAuditPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
