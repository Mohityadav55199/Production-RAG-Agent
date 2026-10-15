import { AppShell } from "@/components/layout/app-shell";
import { NetworkCheck } from "@/components/settings/network-check";
import { SettingsPanel } from "@/components/settings/settings-panel";
import { PageHeader } from "@/components/layout/page-header";

export default function SettingsPage() {
  return (
    <AppShell activePath="/settings">
      <PageHeader title="Settings" description="System health and service status" />

      <SettingsPanel />
      <NetworkCheck />
    </AppShell>
  );
}
