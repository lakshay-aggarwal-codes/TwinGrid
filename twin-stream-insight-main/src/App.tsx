import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import LiveTwin from "./pages/LiveTwin";
import NotFound from "./pages/NotFound";
import { loadLegacyPage } from "./pages/lazyPages";
import { SimulationProvider } from "@/hooks/SimulationProvider";
import { RotateTransition } from "@/components/transition/RotateTransition";

// The legacy KPI dashboard (and recharts with it) is only needed on /legacy,
// so it is loaded on demand instead of shipping in the homepage bundle.
const Index = lazy(loadLegacyPage);

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
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
          {/* Old KPI-card dashboard, kept for reference only (see Stage 0 audit) --
              not the homepage: the brief's core product principle is that the 3D
              twin, not a dashboard, is the primary interface. */}
          <Route path="/legacy" element={<Index />} />
          {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
          <Route path="*" element={<NotFound />} />
        </Routes>
        </Suspense>
        </RotateTransition>
        </SimulationProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
