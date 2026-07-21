import { useSession } from "@oral/stores";
import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Shell from "./shell/Shell";
import ActivatePage from "./pages/ActivatePage";
import AccountPage from "./pages/AccountPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import AssetsPage from "./pages/AssetsPage";
import AvatarsPage from "./pages/AvatarsPage";
import CreatePage from "./pages/CreatePage";
import DashboardPage from "./pages/DashboardPage";
import EditorPage from "./pages/EditorPage";
import ImCenterPage from "./pages/ImCenterPage";
import ImRulesPage from "./pages/ImRulesPage";
import LoginPage from "./pages/LoginPage";
import PersonasPage from "./pages/PersonasPage";
import PublishAccountsPage from "./pages/PublishAccountsPage";
import PublishJobsPage from "./pages/PublishJobsPage";
import ScriptDetailPage from "./pages/ScriptDetailPage";
import ScriptsPage from "./pages/ScriptsPage";
import SettingsPage from "./pages/SettingsPage";
import TaskDetailPage from "./pages/TaskDetailPage";
import TasksPage from "./pages/TasksPage";
import TemplatesPage from "./pages/TemplatesPage";
import VoicesPage from "./pages/VoicesPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, ready, bootstrap } = useSession();
  const location = useLocation();

  useEffect(() => {
    if (!ready) void bootstrap();
  }, [ready, bootstrap]);

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-brand-from border-t-transparent" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/activate" element={<ActivatePage />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/create" element={<CreatePage />} />
        <Route path="/scripts" element={<ScriptsPage />} />
        <Route path="/scripts/:id" element={<ScriptDetailPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/tasks/:id" element={<TaskDetailPage />} />
        <Route path="/assets/personas" element={<PersonasPage />} />
        <Route path="/assets/voices" element={<VoicesPage />} />
        <Route path="/assets/avatars" element={<AvatarsPage />} />
        <Route path="/assets/materials" element={<AssetsPage />} />
        <Route path="/assets/templates" element={<TemplatesPage />} />
        <Route path="/editor" element={<EditorPage />} />
        <Route path="/publish/jobs" element={<PublishJobsPage />} />
        <Route path="/publish/logs" element={<PublishJobsPage showLogs />} />
        <Route path="/publish/accounts" element={<PublishAccountsPage />} />
        <Route path="/im" element={<ImCenterPage />} />
        <Route path="/im/rules" element={<ImRulesPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
