import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthModeSync } from "@/components/auth/AuthModeSync";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AdminShell } from "@/components/admin/AdminShell";
import { AppShell } from "@/components/layout/AppShell";
import AdminCompetitors from "./pages/admin/AdminCompetitors";
import AdminDashboard from "./pages/admin/AdminDashboard";
import AdminNotifications from "./pages/admin/AdminNotifications";
import AdminSettings from "./pages/admin/AdminSettings";
import AdminShops from "./pages/admin/AdminShops";
import AdminFinancial from "./pages/admin/AdminFinancial";
import AdminCampaigns from "./pages/admin/AdminCampaigns";
import AdminAssistant from "./pages/admin/AdminAssistant";
import Overview from "./pages/Overview";
import Queue from "./pages/Queue";
import Inventory from "./pages/Inventory";
import Promotions from "./pages/Promotions";
import Financial from "./pages/Financial";
import Ops from "./pages/Ops";
import FinancialBalanceSheet from "./pages/financial/BalanceSheet";
import FinancialProfitability from "./pages/financial/Profitability";
import FinancialCashflow from "./pages/financial/Cashflow";
import FinancialCosts from "./pages/financial/Costs";
import FinancialAlerts from "./pages/financial/Alerts";
import FinancialProgress from "./pages/financial/Progress";
import FinancialOutcomes from "./pages/financial/Outcomes";
import UpdateFinancials from "./pages/financial/UpdateFinancials";
import NotFound from "./pages/NotFound";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ShopProfile from "./pages/ShopProfile";
import ChatAssistant from "./pages/assistant/ChatAssistant";
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
              <Route path="/promotions" element={<Promotions />} />
              <Route path="/financial" element={<Financial />} />
              <Route path="/financial/balance-sheet" element={<FinancialBalanceSheet />} />
              <Route path="/financial/profitability" element={<FinancialProfitability />} />
              <Route path="/financial/cashflow" element={<FinancialCashflow />} />
              <Route path="/financial/costs" element={<FinancialCosts />} />
              <Route path="/financial/alerts" element={<FinancialAlerts />} />
              <Route path="/financial/progress" element={<FinancialProgress />} />
              <Route path="/financial/outcomes" element={<FinancialOutcomes />} />
              <Route path="/financial/update" element={<UpdateFinancials />} />
              <Route path="/closed-loop" element={<FinancialOutcomes />} />
              <Route path="/upload" element={<Navigate to="/inventory" replace />} />
              <Route path="/audit" element={<Navigate to="/overview" replace />} />
              <Route path="/ops" element={<Ops />} />
              <Route path="/assistant" element={<ChatAssistant />} />
              <Route path="/shop-profile" element={<ShopProfile />} />
              <Route path="/settings" element={<Navigate to="/shop-profile" replace />} />
            </Route>
          </Route>
          <Route element={<ProtectedRoute roles={["admin"]} />}>
            <Route element={<AdminShell />}>
              <Route path="/admin" element={<AdminDashboard />} />
              <Route path="/admin/financial" element={<AdminFinancial />} />
              <Route path="/admin/campaigns" element={<AdminCampaigns />} />
              <Route path="/admin/assistant" element={<AdminAssistant />} />
              <Route path="/admin/shops" element={<AdminShops />} />
              <Route path="/admin/competitor-requests" element={<Navigate to="/admin/notifications" replace />} />
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
