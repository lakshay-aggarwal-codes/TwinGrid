import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import LiveTwin from "./pages/LiveTwin";
import NotFound from "./pages/NotFound";
import { loadAnalyticsPage } from "./pages/lazyPages";
import { SimulationProvider } from "@/hooks/SimulationProvider";
import { RotateTransition } from "@/components/transition/RotateTransition";
import { AuthGate } from "@/components/AuthGate";
import { AppErrorBoundary, RouteErrorBoundary } from "@/state/AppErrorBoundary";
import { createAppQueryClient } from "@/state/queryClient";

// The Analytics view (KPI cards, 24h simulation, what-if, sustainability --
// and recharts with it) is only needed on /analytics,
// so it is loaded on demand instead of shipping in the homepage bundle.
const Index = lazy(loadAnalyticsPage);
// FE-16: the run workflow page, loaded on demand.
const Runs = lazy(() => import("./pages/Runs"));
// FE-17: backend policy-evaluation reports, loaded on demand.
const Evaluation = lazy(() => import("./pages/Evaluation"));

// FE-03: explicit staleTime, no retry on 4xx (see src/state/queryClient.ts).
const queryClient = createAppQueryClient();

const App = () => (
  <AppErrorBoundary scope="app" recovery="reload">
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AuthGate>
        <SimulationProvider>
        <RotateTransition>
        <Suspense
          fallback={
            <div role="status" className="h-full flex items-center justify-center text-sm text-muted-foreground">
              Loading…
            </div>
          }
        >
        <RouteErrorBoundary>
        <Routes>
          <Route path="/" element={<LiveTwin />} />
          {/* Stage 20: the former "legacy" dashboard is now the Analytics view --
              the chart-heavy second page. The 3D twin stays the homepage: the
              brief's core product principle is that the twin, not a dashboard,
              is the primary interface. */}
          <Route path="/analytics" element={<Index />} />
          {/* FE-16: run workflow. The run id in the URL lets a reload recover the run. */}
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<Runs />} />
          {/* FE-17: evaluation reports (BC-11). */}
          <Route path="/evaluation" element={<Evaluation />} />
          <Route path="/evaluation/:id" element={<Evaluation />} />
          {/* Old bookmarks/links keep working. */}
          <Route path="/legacy" element={<Navigate to="/analytics" replace />} />
          {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
          <Route path="*" element={<NotFound />} />
        </Routes>
        </RouteErrorBoundary>
        </Suspense>
        </RotateTransition>
        </SimulationProvider>
        </AuthGate>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
  </AppErrorBoundary>
);

export default App;
