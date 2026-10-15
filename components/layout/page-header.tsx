import { HealthPill } from "@/components/layout/health-pill";

/** Compact page title row; system health sits at the top right. */
export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight sm:text-xl">{title}</h1>
        {description && <p className="mt-0.5 hidden text-sm text-muted-foreground sm:block">{description}</p>}
      </div>
      <HealthPill className="self-start sm:shrink-0" />
    </div>
  );
}
