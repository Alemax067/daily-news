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

export function useSubscriptionPreview(id: string | undefined) {
  return useQuery({
    queryKey: ["subscription", id, "preview"],
    queryFn: () => api.listPreviewNews(id!),
    enabled: !!id,
  });
}

export function useSubscriptionSessionLookup(id: string | undefined) {
  return useQuery({
    queryKey: ["subscription", id, "session"],
    queryFn: () => api.getSubscriptionSession(id!),
    enabled: !!id,
  });
}

export function useSubscriptionTasks(id: string | undefined) {
  return useQuery({
    queryKey: ["subscription", id, "tasks"],
    queryFn: () => api.listSubscriptionTasks(id!),
    enabled: !!id,
    refetchInterval: 5000,
  });
}

export function useNewsDetail(id: number | undefined) {
  return useQuery({
    queryKey: ["news", id],
    queryFn: () => api.getNews(id!),
    enabled: typeof id === "number",
  });
}

export function usePreviewNewsDetail(id: number | undefined) {
  return useQuery({
    queryKey: ["preview-news", id],
    queryFn: () => api.getPreviewNews(id!),
    enabled: typeof id === "number",
  });
}

export function useRefreshPreview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.refreshPreview,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      qc.invalidateQueries({ queryKey: ["subscription", id] });
      qc.invalidateQueries({ queryKey: ["subscription", id, "preview"] });
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

export function usePatchSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, auto_enabled }: { id: string; auto_enabled: boolean }) =>
      api.patchSubscription(id, { auto_enabled }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["subscriptions"] });
      qc.invalidateQueries({ queryKey: ["subscription", vars.id] });
    },
  });
}

// ===== automation =====

export function useAutomationSettings() {
  return useQuery({
    queryKey: ["automation", "settings"],
    queryFn: api.getAutomationSettings,
  });
}

export function useAutomationQueue() {
  return useQuery({
    queryKey: ["automation", "queue"],
    queryFn: api.getAutomationQueue,
    refetchInterval: 5000,
  });
}

export function useSetAutomationSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.setAutomationSettings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["automation", "settings"] });
    },
  });
}

export function useTriggerAutomation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.triggerAutomation,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["automation", "queue"] });
    },
  });
}
