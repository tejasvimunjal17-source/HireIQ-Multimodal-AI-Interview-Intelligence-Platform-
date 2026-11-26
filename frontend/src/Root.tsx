import { useEffect, useState } from "react";
import App from "./App";
import { DashboardPage } from "./pages/DashboardPage";

export const DASHBOARD_HASH = "#/dashboard";

/** Candidates keep the interview app at "/"; hiring managers open "/#/dashboard". Candidates are never shown a link to it. */
export default function Root() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash === DASHBOARD_HASH ? <DashboardPage /> : <App />;
}
