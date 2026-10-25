import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export const useConfig = () => useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: Infinity });

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000, retry: false });

export const useModelCard = () =>
  useQuery({ queryKey: ["model-card"], queryFn: api.modelCard, staleTime: Infinity });

export const useRuns = () => useQuery({ queryKey: ["runs"], queryFn: () => api.runs(50) });
