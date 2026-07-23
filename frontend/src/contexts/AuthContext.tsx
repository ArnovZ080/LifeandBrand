import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import api from "../hooks/useApi";

interface AuthUser {
  id: number;
  email: string;
  name: string;
  role: string;
  org_unit_id: number;
  org_unit_name: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  orgUnitId: number;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  setActiveOrgUnit: (id: number) => void;
  activeOrgUnitId: number;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const ROLES_WITH_MULTI_SITE = ["area_manager", "regional_manager", "national_ops", "md", "ceo"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  // activeOrgUnitId is what components should use — defaults to user's home unit,
  // but AM+ can switch it to any site in their subtree
  const [activeOrgUnitId, setActiveOrgUnitId] = useState<number>(1);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      setIsLoading(false);
      return;
    }
    api.get("/auth/me")
      .then(r => {
        setUser(r.data);
        setActiveOrgUnitId(r.data.org_unit_id);
      })
      .catch(() => localStorage.removeItem("access_token"))
      .finally(() => setIsLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const params = new URLSearchParams();
    params.append("username", email);
    params.append("password", password);
    const r = await api.post("/auth/login", params, {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    localStorage.setItem("access_token", r.data.access_token);
    const me = await api.get("/auth/me");
    setUser(me.data);
    setActiveOrgUnitId(me.data.org_unit_id);
  }

  function logout() {
    localStorage.removeItem("access_token");
    setUser(null);
    setActiveOrgUnitId(1);
  }

  function setActiveOrgUnit(id: number) {
    setActiveOrgUnitId(id);
  }

  return (
    <AuthContext.Provider value={{
      user,
      orgUnitId: activeOrgUnitId,
      isLoading,
      login,
      logout,
      setActiveOrgUnit,
      activeOrgUnitId,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export { ROLES_WITH_MULTI_SITE };
