import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "./context/AuthContext";
import LayoutWithSidebar from "./components/LayoutWithSidebar";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Frontier AI Radar",
  description: "AI competitive intelligence platform — track, benchmark, and analyze frontier AI models.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="overflow-x-hidden dark">
      <body className={`${inter.variable} antialiased overflow-x-hidden`}>
        <AuthProvider>
          <LayoutWithSidebar>{children}</LayoutWithSidebar>
        </AuthProvider>
      </body>
    </html>
  );
}
