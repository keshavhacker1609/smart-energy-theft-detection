import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { ActiveRunContext, type ActiveRunState, type ForecastInput } from "@/hooks/useActiveRun";
import { api, ApiError } from "@/lib/api";
import type { ForecastRun } from "@/lib/types";

const STORAGE_KEY = "gridcast-active-run";

function readStoredId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeId(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Remembering the last run is a convenience only.
  }
}

async function loadSampleFile(): Promise<File> {
  const response = await fetch(`${import.meta.env.BASE_URL}sample_test_input.csv`);
  if (!response.ok) {
    throw new ApiError(response.status, { detail: "Sample telemetry file could not be loaded." });
  }
  return new File([await response.blob()], "sample_test_input.csv", { type: "text/csv" });
}

export function ActiveRunProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [runId, setRunId] = useState<string | null>(readStoredId);

  const latest = useQuery({
    queryKey: ["runs", "latest"],
    queryFn: async () => (await api.runs(1))[0]?.id ?? null,
    enabled: runId === null,
    retry: 1,
  });
  const effectiveId = runId ?? latest.data ?? null;

  const runQuery = useQuery({
    queryKey: ["run", effectiveId],
    queryFn: () => api.run(effectiveId as string),
    enabled: effectiveId !== null,
    staleTime: Infinity,
    retry: (count, error) => error instanceof ApiError && error.status !== 404 && count < 2,
  });

  const select = useCallback((id: string) => {
    setRunId(id);
    storeId(id);
  }, []);

  const mutation = useMutation({
    mutationFn: async (input: ForecastInput): Promise<ForecastRun> => {
      if (input.kind === "upload") return api.upload(input.file, input.battery);
      if (input.kind === "manual") return api.manual(input.rows, input.battery);
      return api.upload(await loadSampleFile());
    },
    onSuccess: (run, input) => {
      queryClient.setQueryData(["run", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      select(run.id);
      if (run.storage_warning) {
        toast.warning("Forecast ready but not saved to history", { description: run.storage_warning });
      } else {
        toast.success(`Forecast ready: ${run.hours.length} hours from ${run.filename ?? "manual entry"}`);
      }
      if (!input.stay) navigate("/");
    },
    onError: (error, input) => {
      const apiError = error instanceof ApiError ? error : null;
      toast.error("Forecast failed", {
        description: apiError?.message ?? "Unexpected error. Retry, or check the input file.",
        action: apiError?.retryable ? { label: "Retry", onClick: () => mutation.mutate(input) } : undefined,
      });
    },
  });

  const value = useMemo<ActiveRunState>(
    () => ({
      runId: effectiveId,
      run: runQuery.data,
      isLoading: runQuery.isLoading || (runId === null && latest.isLoading),
      error:
        (runQuery.error ?? latest.error) instanceof ApiError
          ? ((runQuery.error ?? latest.error) as ApiError)
          : null,
      select,
      forecast: mutation.mutate,
      isForecasting: mutation.isPending,
      lastError: mutation.error instanceof ApiError ? mutation.error : null,
    }),
    [
      effectiveId,
      runQuery.data,
      runQuery.isLoading,
      runQuery.error,
      runId,
      latest.isLoading,
      latest.error,
      select,
      mutation.mutate,
      mutation.isPending,
      mutation.error,
    ],
  );

  return <ActiveRunContext.Provider value={value}>{children}</ActiveRunContext.Provider>;
}
