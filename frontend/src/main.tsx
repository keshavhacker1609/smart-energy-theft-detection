import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router";
import { Toaster } from "sonner";
import { App } from "./App";
import { TooltipProvider } from "./components/ui/tooltip";
import { ActiveRunProvider } from "./components/ActiveRunProvider";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

const root = document.getElementById("root");
if (!root) throw new Error("root element missing");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <TooltipProvider delayDuration={150}>
          <ActiveRunProvider>
            <App />
          </ActiveRunProvider>
        </TooltipProvider>
      </HashRouter>
      <Toaster
        position="bottom-right"
        closeButton
        toastOptions={{ className: "!bg-raised !text-fg !border-border-strong" }}
      />
    </QueryClientProvider>
  </StrictMode>,
);
