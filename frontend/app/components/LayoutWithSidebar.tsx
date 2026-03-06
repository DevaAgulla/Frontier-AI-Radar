"use client";

import { usePathname } from "next/navigation";
import Header from "./Header";
import Sidebar from "./Sidebar";
import LandingPage from "./LandingPage";
import { RunConfigProvider } from "../context/RunConfigContext";
import { ToastProvider } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import ToastViewport from "./ToastViewport";

export default function LayoutWithSidebar({ children }: { readonly children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, loading } = useAuth();

  // Auth pages get rendered without sidebar/header (full-page layout)
  const isAuthPage = pathname.startsWith("/auth/");

  if (isAuthPage) {
    return (
      <ToastProvider>
        <RunConfigProvider>
          {children}
          <ToastViewport />
        </RunConfigProvider>
      </ToastProvider>
    );
  }

  // Show loading spinner while checking auth
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-[var(--primary)] flex items-center justify-center animate-pulse">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
              <circle cx="12" cy="12" r="2.5" />
              <circle cx="12" cy="12" r="6" strokeOpacity="0.6" />
              <line x1="12" y1="12" x2="12" y2="2" />
            </svg>
          </div>
          <p className="text-sm text-[var(--text-muted)]">Loading…</p>
        </div>
      </div>
    );
  }

  // Not authenticated → show landing page
  if (!user) {
    return <LandingPage />;
  }

  // Authenticated → show normal app layout
  return (
    <ToastProvider>
      <RunConfigProvider>
        <Header />
        <Sidebar>{children}</Sidebar>
        <ToastViewport />
      </RunConfigProvider>
    </ToastProvider>
  );
}
