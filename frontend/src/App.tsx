import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AutomationPage } from "./pages/AutomationPage";
import { AutomationSubscriptionPage } from "./pages/AutomationSubscriptionPage";
import { NewSubscriptionPage } from "./pages/NewSubscriptionPage";
import { NewsDetailPage } from "./pages/NewsDetailPage";
import { SubscriptionDetailPage } from "./pages/SubscriptionDetailPage";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { TimelinePage } from "./pages/TimelinePage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/new" replace />} />
        <Route path="new" element={<NewSubscriptionPage />} />
        <Route path="subscriptions" element={<SubscriptionsPage />} />
        <Route path="subscriptions/:id" element={<SubscriptionDetailPage />} />
        <Route path="automation" element={<AutomationPage />} />
        <Route
          path="automation/subscriptions/:id"
          element={<AutomationSubscriptionPage />}
        />
        <Route path="timeline" element={<TimelinePage />} />
        <Route path="news/:id" element={<NewsDetailPage />} />
      </Route>
    </Routes>
  );
}
