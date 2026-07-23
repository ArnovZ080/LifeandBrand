import { Routes, Route, NavLink, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import Dashboard from "./pages/Dashboard";
import Suppliers from "./pages/Suppliers";
import PurchaseOrders from "./pages/PurchaseOrders";
import Deliveries from "./pages/Deliveries";
import SpotChecks from "./pages/SpotChecks";
import InvoiceOCR from "./pages/InvoiceOCR";
import Alerts from "./pages/Alerts";
import AMOperatingStructure from "./pages/AMOperatingStructure";
import OpsVisitReport from "./pages/OpsVisitReport";
import OneOnOne from "./pages/OneOnOne";
import Login from "./pages/Login";
import { useAuth, ROLES_WITH_MULTI_SITE } from "./contexts/AuthContext";
import api from "./hooks/useApi";

const stockNavItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/spot-checks", label: "Spot Checks" },
  { to: "/alerts", label: "Freshness Alerts" },
  { to: "/suppliers", label: "Suppliers" },
  { to: "/purchase-orders", label: "Purchase Orders" },
  { to: "/deliveries", label: "Deliveries (GRN)" },
  { to: "/invoice-ocr", label: "Invoice Capture" },
];

const amNavItems = [
  { to: "/am/operating-structure", label: "Operating Structure" },
  { to: "/am/ops-visits", label: "OPS Visit Reports" },
  { to: "/am/one-on-ones", label: "One-on-One Meetings" },
];

function NavSection({ label, items }: { label: string; items: { to: string; label: string; end?: boolean }[] }) {
  return (
    <>
      <div style={{ padding: "8px 20px 4px", fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", color: "rgba(255,255,255,0.35)", textTransform: "uppercase" }}>
        {label}
      </div>
      {items.map(item => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          style={({ isActive }) => ({
            display: "block", padding: "10px 20px",
            color: isActive ? "var(--color-sidebar-active)" : "var(--color-sidebar-text)",
            background: isActive ? "rgba(255,255,255,0.08)" : "transparent",
            borderLeft: isActive ? "3px solid var(--color-primary)" : "3px solid transparent",
            fontSize: 13,
          })}
        >
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

function OrgUnitSwitcher() {
  const { user, activeOrgUnitId, setActiveOrgUnit } = useAuth();
  const canSwitch = user && ROLES_WITH_MULTI_SITE.includes(user.role);

  const { data: units = [] } = useQuery({
    queryKey: ["org-units-list"],
    queryFn: () => api.get("/org-units/").then(r => r.data),
    enabled: !!canSwitch,
  });

  if (!canSwitch || units.length <= 1) return null;

  return (
    <div style={{ padding: "0 12px 12px" }}>
      <select
        value={activeOrgUnitId}
        onChange={e => setActiveOrgUnit(Number(e.target.value))}
        style={{
          width: "100%", fontSize: 11, padding: "5px 8px",
          background: "rgba(255,255,255,0.1)", color: "#fff",
          border: "1px solid rgba(255,255,255,0.2)", borderRadius: 4,
        }}
      >
        {units.map((u: any) => (
          <option key={u.id} value={u.id} style={{ background: "#1e293b", color: "#fff" }}>
            {u.name}
          </option>
        ))}
      </select>
    </div>
  );
}

function AppLayout() {
  const { user, logout, isLoading } = useAuth();

  if (isLoading) {
    return <div style={{ padding: 32, color: "var(--color-text-muted)" }}>Loading...</div>;
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <nav style={{ width: 220, background: "var(--color-sidebar)", padding: "24px 0", flexShrink: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "0 20px 16px", color: "#fff", fontWeight: 700, fontSize: 15 }}>
          Life & Brand
          <div style={{ color: "var(--color-sidebar-text)", fontWeight: 400, fontSize: 12, marginTop: 2 }}>
            Operations Platform
          </div>
        </div>

        <OrgUnitSwitcher />

        <div style={{ flex: 1 }}>
          <NavSection label="Stock Control" items={stockNavItems} />
          <div style={{ margin: "12px 20px", borderBottom: "1px solid rgba(255,255,255,0.1)" }} />
          <NavSection label="Area Manager" items={amNavItems} />
        </div>

        {/* User footer */}
        <div style={{ padding: "12px 20px", borderTop: "1px solid rgba(255,255,255,0.1)", marginTop: 8 }}>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", marginBottom: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {user.name}
          </div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", marginBottom: 6 }}>
            {user.role.replace(/_/g, " ")}
          </div>
          <button
            onClick={logout}
            className="secondary"
            style={{ fontSize: 11, padding: "4px 8px", width: "100%" }}
          >
            Sign out
          </button>
        </div>
      </nav>

      <main style={{ flex: 1, padding: "28px 32px", overflowY: "auto" }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/spot-checks" element={<SpotChecks />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/suppliers" element={<Suppliers />} />
          <Route path="/purchase-orders" element={<PurchaseOrders />} />
          <Route path="/deliveries" element={<Deliveries />} />
          <Route path="/invoice-ocr" element={<InvoiceOCR />} />
          <Route path="/am/operating-structure" element={<AMOperatingStructure />} />
          <Route path="/am/ops-visits" element={<OpsVisitReport />} />
          <Route path="/am/one-on-ones" element={<OneOnOne />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/*" element={<AppLayout />} />
    </Routes>
  );
}

function LoginRoute() {
  const { user, isLoading } = useAuth();
  if (isLoading) return null;
  if (user) return <Navigate to="/" replace />;
  return <Login />;
}
