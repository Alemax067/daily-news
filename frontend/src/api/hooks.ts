import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export function useSubscriptions() {
  return useQuery({ queryKey: ["subscriptions"], queryFn: api.listSubscriptions });
}

export function useSubscription(id: string | undefined) {
  return useQuery({
    queryKey: ["subscription", id],
    queryFn: () => api.getSubscription(id!),
    enabled: !!id,
  });
}

export function useSubscriptionNews(id: string | undefined) {
  return useQuery({
    queryKey: ["subscription", id, "news"],
    queryFn: () => api.listSubscriptionNews(id!),
    enabled: !!id,
  });
}

export function useNewsDetail(id: number | undefined) {
  return useQuery({
    queryKey: ["news", id],
    queryFn: () => api.getNews(id!),
    enabled: typeof id === "number",
  });
}

export function useRefreshSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.refreshSubscription,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      qc.invalidateQueries({ queryKey: ["subscription", id] });
      qc.invalidateQueries({ queryKey: ["subscription", id, "news"] });
    },
  });
}

export function useDeleteSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteSubscription,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
    },
  });
}
