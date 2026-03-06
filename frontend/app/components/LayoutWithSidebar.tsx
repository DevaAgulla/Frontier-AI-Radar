"use client";

import Header from "./Header";
import Sidebar from "./Sidebar";
import { RunConfigProvider } from "../context/RunConfigContext";
import { ToastProvider } from "../context/ToastContext";
import ToastViewport from "./ToastViewport";

export default function LayoutWithSidebar({ children }: { readonly children: React.ReactNode }) {
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
