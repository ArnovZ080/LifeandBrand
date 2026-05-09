import { Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Suppliers from "./pages/Suppliers";
import PurchaseOrders from "./pages/PurchaseOrders";
import Deliveries from "./pages/Deliveries";
import SpotChecks from "./pages/SpotChecks";
import InvoiceOCR from "./pages/InvoiceOCR";
import Alerts from "./pages/Alerts";

const navItems = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/spot-checks", label: "Spot Checks" },
  { to: "/alerts", label: "Freshness Alerts" },
  { to: "/suppliers", label: "Suppliers" },
  { to: "/purchase-orders", label: "Purchase Orders" },
  { to: "/deliveries", label: "Deliveries (GRN)" },
  { to: "/invoice-ocr", label: "Invoice Capture" },
];

export default function App() {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <nav style={{
        width: 220,
        background: "var(--color-sidebar)",
        padding: "24px 0",
        flexShrink: 0,
      }}>
        <div style={{ padding: "0 20px 24px", color: "#fff", fontWeight: 700, fontSize: 15 }}>
          Life & Brand
          <div style={{ color: "var(--color-sidebar-text)", fontWeight: 400, fontSize: 12, marginTop: 2 }}>
            Stock Control
          </div>
        </div>
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            style={({ isActive }) => ({
              display: "block",
              padding: "10px 20px",
              color: isActive ? "var(--color-sidebar-active)" : "var(--color-sidebar-text)",
              background: isActive ? "rgba(255,255,255,0.08)" : "transparent",
              borderLeft: isActive ? "3px solid var(--color-primary)" : "3px solid transparent",
              fontSize: 13,
            })}
          >
            {item.label}
          </NavLink>
        ))}
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
        </Routes>
      </main>
    </div>
  );
}
