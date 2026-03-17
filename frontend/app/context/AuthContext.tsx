"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  is_admin?: boolean;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  signin: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  signup: (name: string, email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  signout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: null,
  loading: true,
  signin: async () => ({ ok: false }),
  signup: async () => ({ ok: false }),
  signout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

const TOKEN_KEY = "frontier_ai_radar_token";
const USER_KEY  = "frontier_ai_radar_user";

/** Fire-and-forget prefetch — warms Redis for all slow API calls. */
function triggerPrefetch(userId: number, token: string) {
  fetch(`/api/prefetch?user_id=${userId}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).catch(() => {/* best-effort — ignore errors */});
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore session from localStorage on mount
  useEffect(() => {
    try {
      const storedToken = localStorage.getItem(TOKEN_KEY);
      const storedUser = localStorage.getItem(USER_KEY);
      if (storedToken && storedUser) {
        setToken(storedToken);
        setUser(JSON.parse(storedUser));

        // Verify token is still valid with backend
        fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${storedToken}` },
        })
          .then((res) => {
            if (!res.ok) {
              // Token expired or invalid — clear session
              localStorage.removeItem(TOKEN_KEY);
              localStorage.removeItem(USER_KEY);
              setToken(null);
              setUser(null);
            } else {
              // Valid session restored — warm the cache in the background
              const restoredUser = JSON.parse(storedUser);
              triggerPrefetch(restoredUser.id, storedToken);
            }
          })
          .catch(() => {
            // Network error — keep session (offline-friendly)
          })
          .finally(() => setLoading(false));
      } else {
        setLoading(false);
      }
    } catch {
      setLoading(false);
    }
  }, []);

  const signin = useCallback(async (email: string, password: string) => {
    try {
      const res = await fetch("/api/auth/signin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        return { ok: false, error: data.error || data.detail || "Sign in failed" };
      }
      const { token: newToken, user: newUser } = data;
      localStorage.setItem(TOKEN_KEY, newToken);
      localStorage.setItem(USER_KEY, JSON.stringify(newUser));
      setToken(newToken);
      setUser(newUser);
      triggerPrefetch(newUser.id, newToken);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : "Network error" };
    }
  }, []);

  const signup = useCallback(async (name: string, email: string, password: string) => {
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        return { ok: false, error: data.error || data.detail || "Sign up failed" };
      }
      const { token: newToken, user: newUser } = data;
      localStorage.setItem(TOKEN_KEY, newToken);
      localStorage.setItem(USER_KEY, JSON.stringify(newUser));
      setToken(newToken);
      setUser(newUser);
      triggerPrefetch(newUser.id, newToken);
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : "Network error" };
    }
  }, []);

  const signout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, loading, signin, signup, signout }}>
      {children}
    </AuthContext.Provider>
  );
}
