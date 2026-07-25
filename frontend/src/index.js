import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/index.css";
import App from "@/App";

// Monaco / resizable panels can trigger this; it is benign but CRA's overlay treats it as fatal.
window.addEventListener("error", (event) => {
  const msg = event.message || "";
  if (
    msg.includes("ResizeObserver loop completed with undelivered notifications") ||
    msg.includes("ResizeObserver loop limit exceeded")
  ) {
    event.stopImmediatePropagation();
  }
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
});

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
