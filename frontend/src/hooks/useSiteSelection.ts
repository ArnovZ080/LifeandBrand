import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import api from "./useApi";
import { useAuth } from "../contexts/AuthContext";

interface OrgUnit { id: number; tier: string; }

/**
 * Site picked for the page. Starts at the active org unit when that unit is a
 * site, otherwise at the first site the user can see. Returns null while the
 * site list is loading or when there are no sites.
 */
export function useSiteSelection(): [number | null, (id: number) => void] {
  const { activeOrgUnitId } = useAuth();
  const [picked, setPicked] = useState<number | null>(null);
  const { data: units = [] } = useQuery<OrgUnit[]>({
    queryKey: ["org-units-sites"],
    queryFn: () => api.get("/org-units/?tier=site").then(r => r.data),
  });
  const sites = units.filter(u => u.tier === "site");
  const fallback = sites.find(s => s.id === activeOrgUnitId)?.id ?? sites[0]?.id ?? null;
  return [picked ?? fallback, setPicked];
}
