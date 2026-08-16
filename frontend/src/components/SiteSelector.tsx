import { useQuery } from "@tanstack/react-query";
import api from "../hooks/useApi";

interface OrgUnit {
  id: number;
  name: string;
  tier: string;
  code?: string | null;
  pos_site_code?: string | null;
}

interface SiteSelectorProps {
  value: number;
  onChange: (id: number) => void;
}

export default function SiteSelector({ value, onChange }: SiteSelectorProps) {
  // Backend /org-units/ returns a flat list; filter to SITE tier client-side
  // (the ?tier=site param is ignored by the backend but harmless).
  const { data: units = [], isLoading } = useQuery<OrgUnit[]>({
    queryKey: ["org-units-sites"],
    queryFn: () => api.get("/org-units/?tier=site").then(r => r.data),
  });

  const sites = units.filter(u => u.tier === "site");

  return (
    <select
      value={value}
      onChange={e => onChange(Number(e.target.value))}
      disabled={isLoading}
      style={{
        padding: "8px 10px", fontSize: 13,
        border: "1px solid var(--color-border)", borderRadius: 6,
        background: "var(--color-surface)", color: "var(--color-text)",
        minWidth: 220,
      }}
    >
      {isLoading && <option value={value}>Loading sites...</option>}
      {!isLoading && sites.length === 0 && <option value={value}>No sites available</option>}
      {sites.map(site => {
        const code = site.pos_site_code || site.code;
        return (
          <option key={site.id} value={site.id}>
            {site.name}{code ? ` (${code})` : ""}
          </option>
        );
      })}
    </select>
  );
}
