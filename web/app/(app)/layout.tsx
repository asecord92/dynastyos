import { AppNav } from "../components/AppNav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-100 text-gray-900">
      <AppNav />
      <div className="max-w-5xl mx-auto p-6">{children}</div>
    </div>
  );
}