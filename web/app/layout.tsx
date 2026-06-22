import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Inter, Geist } from "next/font/google";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const geist = Geist({ subsets: ["latin"], variable: "--font-display-grotesk", display: "swap" });

export const metadata: Metadata = {
  title: "DynastyOS",
  description: "Fantrax contract dynasty baseball toolkit",
  // Standalone home-screen app: title + status bar styling.
  appleWebApp: {
    capable: true,
    title: "DynastyOS",
    statusBarStyle: "default",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Required for env(safe-area-inset-*) to resolve in a standalone PWA — without
  // it the bottom tab bar sits into the home-indicator curve on iPhone.
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${geist.variable}`}>
      <body>{children}</body>
    </html>
  );
}