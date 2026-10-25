import { Activity, BarChart3, Brain, History, Moon, SlidersHorizontal, Sun, Upload, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useHealth } from "@/hooks/queries";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Dashboard", icon: BarChart3 },
  { to: "/ingest", label: "Ingest", icon: Upload },
  { to: "/simulate", label: "What-if", icon: SlidersHorizontal },
  { to: "/model", label: "Model", icon: Brain },
  { to: "/history", label: "History", icon: History },
];

function HealthIndicator() {
  const health = useHealth();
  const data = health.data;
  const state = health.isError ? "down" : !data ? "pending" : data.status === "ok" ? "ok" : "degraded";
  const label = {
    ok: "All systems reachable",
    degraded: "Degraded",
    down: "API unreachable",
    pending: "Checking services",
  }[state];
  const detail = data ? (
    <div className="space-y-1">
      <div>
        QuickML: {data.quickml.ok ? `reachable (${data.quickml.latency_ms} ms)` : data.quickml.detail}
      </div>
      <div>Storage: {data.storage.ok ? "reachable" : data.storage.detail}</div>
    </div>
  ) : (
    label
  );
  return (
    <Tooltip content={detail}>
      <button
        type="button"
        className="flex items-center gap-2 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-raised"
        aria-label={`Service status: ${label}`}
      >
        <span
          className={cn(
            "size-2 rounded-full",
            state === "ok" && "bg-storage",
            state === "degraded" && "bg-warning-fill",
            state === "down" && "bg-overload",
            state === "pending" && "animate-pulse bg-fg-subtle",
          )}
        />
        <span className="hidden sm:inline">{label}</span>
      </button>
    </Tooltip>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [theme, toggleTheme] = useTheme();
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-40 border-b bg-bg/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4">
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-7 place-items-center rounded-md bg-accent text-white">
              <Zap className="size-4" aria-hidden />
            </span>
            <span>GridCast</span>
            <span className="hidden text-xs font-normal text-fg-subtle md:inline">Microgrid operations</span>
          </NavLink>
          <nav aria-label="Primary" className="hidden flex-1 items-center gap-1 md:flex">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm text-fg-muted transition-colors hover:bg-raised hover:text-fg",
                    isActive && "bg-raised text-fg",
                  )
                }
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <HealthIndicator />
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
          </div>
        </div>
        <nav aria-label="Primary" className="flex gap-1 overflow-x-auto border-t px-2 py-1.5 md:hidden">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs text-fg-muted",
                  isActive && "bg-raised text-fg",
                )
              }
            >
              <Icon className="size-3.5" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 py-5">{children}</main>
      <footer className="mx-auto flex max-w-[1440px] items-center gap-2 px-4 pb-6 text-xs text-fg-subtle">
        <Activity className="size-3.5" aria-hidden />
        Forecasts from the published QuickML endpoint. Controller rules and thresholds come from the API
        configuration.
      </footer>
    </div>
  );
}
