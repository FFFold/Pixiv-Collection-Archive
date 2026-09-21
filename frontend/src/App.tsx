import { useEffect } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { setUnauthorizedHandler } from "./api/client";
import { useMe } from "./api/queries";
import AppLayout from "./components/AppLayout";
import { GalleryFiltersProvider } from "./contexts/GalleryFiltersContext";
import { SelectionProvider } from "./contexts/SelectionContext";
import Export from "./pages/Export";
import Gallery from "./pages/Gallery";
import IllustDetail from "./pages/IllustDetail";
import Login from "./pages/Login";
import Settings from "./pages/Settings";
import Stats from "./pages/Stats";
import Tasks from "./pages/Tasks";

export default function App() {
  const navigate = useNavigate();
  const { data, isLoading } = useMe();

  useEffect(() => {
    setUnauthorizedHandler(() => navigate("/login"));
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-text-muted">加载中…</div>
    );
  }

  const authenticated = data?.authenticated ?? false;

  return (
    <SelectionProvider>
      <GalleryFiltersProvider>
        <Routes>
          <Route
            path="/login"
            element={authenticated ? <Navigate to="/" replace /> : <Login />}
          />
          <Route element={authenticated ? <AppLayout /> : <Navigate to="/login" replace />}>
            <Route path="/" element={<Gallery key="all" />} />
            <Route
              path="/unbookmarked"
              element={<Gallery key="unbookmarked" initialOnlyUnbookmarked />}
            />
            <Route path="/illust/:pid" element={<IllustDetail />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/stats" element={<Stats />} />
            <Route path="/export" element={<Export />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </GalleryFiltersProvider>
    </SelectionProvider>
  );
}
