import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router";
import { AppShell } from "./components/layout/AppShell";
import { Skeleton } from "./components/ui/skeleton";
import { DashboardPage } from "./pages/Dashboard";

const IngestPage = lazy(() => import("./pages/Ingest"));
const SimulatorPage = lazy(() => import("./pages/Simulator"));
const ModelPage = lazy(() => import("./pages/Model"));
const HistoryPage = lazy(() => import("./pages/History"));

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/ingest" element={<IngestPage />} />
          <Route path="/simulate" element={<SimulatorPage />} />
          <Route path="/model" element={<ModelPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="*" element={<DashboardPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
