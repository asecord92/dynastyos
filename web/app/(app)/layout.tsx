import { AppNav } from "../components/AppNav";
import AuthGate from "../components/AuthGate";
import { AutoSync } from "../components/AutoSync";
import { Suspense } from "react";

export const dynamic = "force-dynamic";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <Suspense>
        <div className="min-h-screen bg-gray-100 text-gray-900">
          <AppNav />
          <AutoSync />
          <div className="max-w-5xl mx-auto p-6">{children}</div>
        </div>
      </Suspense>
    </AuthGate>
  );
}