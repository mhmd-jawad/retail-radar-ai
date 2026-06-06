import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthModeSync } from "@/components/auth/AuthModeSync";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AdminShell } from "@/components/admin/AdminShell";
import { AppShell } from "@/components/layout/AppShell";
import AdminCompetitorRequests from "./pages/admin/AdminCompetitorRequests";
import AdminCompetitors from "./pages/admin/AdminCompetitors";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminNotifications from "./pages/admin/AdminNotifications";
import AdminSettings from "./pages/admin/AdminSettings";
import AdminShops from "./pages/admin/AdminShops";
import Overview from "./pages/Overview";
import Queue from "./pages/Queue";
import Inventory from "./pages/Inventory";
import Competitive from "./pages/Competitive";
import Promotions from "./pages/Promotions";
import Financial from "./pages/Financial";
import FinancialBalanceSheet from "./pages/financial/BalanceSheet";
import FinancialProfitability from "./pages/financial/Profitability";
import FinancialCashflow from "./pages/financial/Cashflow";
import FinancialLollar from "./pages/financial/Lollar";
import FinancialCosts from "./pages/financial/Costs";
import FinancialAlerts from "./pages/financial/Alerts";
import UploadBatch from "./pages/UploadBatch";
import Audit from "./pages/Audit";
import Ops from "./pages/Ops";
import SettingsPage from "./pages/Settings";
import NotFound from "./pages/NotFound";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ShopProfile from "./pages/ShopProfile";
import { tenantScopeKey } from "./lib/tenantScope";
import { useAuth } from "./store/auth";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider delayDuration={150}>
      <SessionCacheBoundary />
      <AuthModeSync />
      <Toaster />
      <Sonner position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route element={<ProtectedRoute roles={["shop"]} />}>
            <Route element={<AppShell />}>
              <Route path="/overview" element={<Overview />} />
              <Route path="/queue" element={<Queue />} />
              <Route path="/inventory" element={<Inventory />} />
              <Route path="/competitive" element={<Competitive />} />
              <Route path="/promotions" element={<Promotions />} />
              <Route path="/financial" element={<Financial />} />
              <Route path="/financial/balance-sheet" element={<FinancialBalanceSheet />} />
              <Route path="/financial/profitability" element={<FinancialProfitability />} />
              <Route path="/financial/cashflow" element={<FinancialCashflow />} />
              <Route path="/financial/lollar" element={<FinancialLollar />} />
              <Route path="/financial/costs" element={<FinancialCosts />} />
              <Route path="/financial/alerts" element={<FinancialAlerts />} />
              <Route path="/upload" element={<UploadBatch />} />
              <Route path="/audit" element={<Audit />} />
              <Route path="/ops" element={<Ops />} />
              <Route path="/shop-profile" element={<ShopProfile />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Route>
          <Route element={<ProtectedRoute roles={["admin"]} />}>
            <Route element={<AdminShell />}>
              <Route path="/admin" element={<AdminDashboard />} />
              <Route path="/admin/shops" element={<AdminShops />} />
              <Route path="/admin/competitor-requests" element={<AdminCompetitorRequests />} />
              <Route path="/admin/notifications" element={<AdminNotifications />} />
              <Route path="/admin/competitors" element={<AdminCompetitors />} />
              <Route path="/admin/settings" element={<AdminSettings />} />
            </Route>
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;

function SessionCacheBoundary() {
  const queryClient = useQueryClient();
  const token = useAuth((state) => state.token);
  const role = useAuth((state) => state.user?.global_role);
  const tenantScope = useAuth((state) => tenantScopeKey(state.user));
  const sessionKey = `${token || 'no-token'}::${role || 'no-role'}::${tenantScope}`;
  const previous = useRef(sessionKey);

  useEffect(() => {
    if (previous.current !== sessionKey) {
      queryClient.clear();
      previous.current = sessionKey;
    }
  }, [queryClient, sessionKey]);

  return null;
}
