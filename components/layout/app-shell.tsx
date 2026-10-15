import { RequireAuth } from "@/components/auth/require-auth";
import { AppHeader } from "@/components/layout/app-header";
import { WakingBanner } from "@/components/layout/waking-banner";

export function AppShell({
  activePath,
  children,
}: {
  activePath: string;
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
    <div className="min-h-screen bg-background">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 right-0 h-[500px] w-[500px] rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute -bottom-40 left-0 h-[400px] w-[400px] rounded-full bg-violet-500/5 blur-3xl" />
      </div>

      <WakingBanner />
      <AppHeader activePath={activePath} />

      <main className="relative mx-auto max-w-7xl px-4 py-4 sm:px-6 sm:py-5 lg:px-8">
        {children}
      </main>
    </div>
    </RequireAuth>
  );
}
