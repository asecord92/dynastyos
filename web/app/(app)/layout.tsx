import { AppNav } from "../components/AppNav";
import AuthGate from "../components/AuthGate";
import { AutoSync } from "../components/AutoSync";
import { PullToRefresh } from "../components/PullToRefresh";
import { AiStatusBanner } from "../components/ui/AiStatusBanner";
import { AiStatusSync } from "../components/AiStatusSync";
import { WhatsNewModal } from "../components/WhatsNewModal";
import { AiStatusProvider } from "../lib/aiStatus";
import { Suspense } from "react";

export const dynamic = "force-dynamic";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <Suspense>
        <AiStatusProvider>
          <div className="min-h-screen bg-canvas text-gray-900">
            <AppNav />
            <AutoSync />
            <PullToRefresh />
            <WhatsNewModal />
            <AiStatusSync />
            <AiStatusBanner />
            {/* Extra bottom padding on mobile so content clears the bottom tab bar */}
            <div className="max-w-5xl mx-auto p-6 pb-24 lg:pb-6">{children}</div>
          </div>
        </AiStatusProvider>
      </Suspense>
    </AuthGate>
  );
}