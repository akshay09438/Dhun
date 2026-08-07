import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { AdminScreen } from "./components/screens/AdminScreen";
import "./index.css";

// The internal dev/ops dashboard lives behind a hash route (#dev) on the same app — no router
// needed, and it stays out of the normal 4-step user flow. Visiting <site>/#dev shows it.
const isDev = window.location.hash
  .replace(/^#/, "")
  .toLowerCase()
  .startsWith("dev");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{isDev ? <AdminScreen /> : <App />}</React.StrictMode>,
);
