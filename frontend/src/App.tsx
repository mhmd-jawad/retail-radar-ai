import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppShell } from "@/components/layout/AppShell";
import Overview from "./pages/Overview";
import Queue from "./pages/Queue";
import Inventory from "./pages/Inventory";
import Competitive from "./pages/Competitive";
import Promotions from "./pages/Promotions";
import Financial from "./pages/Financial";
import UploadBatch from "./pages/UploadBatch";
import Audit from "./pages/Audit";
import Ops from "./pages/Ops";
import SettingsPage from "./pages/Settings";
import NotFound from "./pages/NotFound";
import Landing from "./pages/Landing";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider delayDuration={150}>
      <Toaster />
      <Sonner position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route element={<AppShell />}>
            <Route path="/overview" element={<Overview />} />
            <Route path="/queue" element={<Queue />} />
            <Route path="/inventory" element={<Inventory />} />
            <Route path="/competitive" element={<Competitive />} />
            <Route path="/promotions" element={<Promotions />} />
            <Route path="/financial" element={<Financial />} />
            <Route path="/upload" element={<UploadBatch />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/ops" element={<Ops />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
