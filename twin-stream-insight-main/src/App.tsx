import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import LiveTwin from "./pages/LiveTwin";
import NotFound from "./pages/NotFound";
import { loadAnalyticsPage } from "./pages/lazyPages";
import { SimulationProvider } from "@/hooks/SimulationProvider";
import { RotateTransition } from "@/components/transition/RotateTransition";
import { AuthGate } from "@/components/AuthGate";

// The Analytics view (KPI cards, 24h simulation, what-if, sustainability --
// and recharts with it) is only needed on /analytics,
// so it is loaded on demand instead of shipping in the homepage bundle.
const Index = lazy(loadAnalyticsPage);

const queryClient = new QueryClient();

const App = () => (
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
        <Routes>
          <Route path="/" element={<LiveTwin />} />
          {/* Stage 20: the former "legacy" dashboard is now the Analytics view --
              the chart-heavy second page. The 3D twin stays the homepage: the
              brief's core product principle is that the twin, not a dashboard,
              is the primary interface. */}
          <Route path="/analytics" element={<Index />} />
          {/* Old bookmarks/links keep working. */}
          <Route path="/legacy" element={<Navigate to="/analytics" replace />} />
          {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
          <Route path="*" element={<NotFound />} />
        </Routes>
        </Suspense>
        </RotateTransition>
        </SimulationProvider>
        </AuthGate>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
