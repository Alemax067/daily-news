import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { NewSubscriptionPage } from "./pages/NewSubscriptionPage";
import { SubscriptionsPage } from "./pages/SubscriptionsPage";
import { SubscriptionDetailPage } from "./pages/SubscriptionDetailPage";
import { NewsDetailPage } from "./pages/NewsDetailPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/new" replace />} />
        <Route path="new" element={<NewSubscriptionPage />} />
        <Route path="subscriptions" element={<SubscriptionsPage />} />
        <Route path="subscriptions/:id" element={<SubscriptionDetailPage />} />
        <Route path="news/:id" element={<NewsDetailPage />} />
      </Route>
    </Routes>
  );
}
