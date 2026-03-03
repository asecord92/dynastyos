import { AppNav } from "../components/AppNav";
import AuthGate from "../components/AuthGate";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="min-h-screen bg-gray-100 text-gray-900">
        <AppNav />
        <div className="max-w-5xl mx-auto p-6">{children}</div>
      </div>
    </AuthGate>
  );
}