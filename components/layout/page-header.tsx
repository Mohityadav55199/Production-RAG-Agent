import { HealthPill } from "@/components/layout/health-pill";
import { cn } from "@/lib/utils";

/** Compact page title with system health at the top left, under the title. */
export function PageHeader({ title, description, className }: { title: string; description?: string; className?: string }) {
  return (
    <div className={cn("mb-4 flex flex-col items-start gap-2", className)}>
      <div className="min-w-0">
        <h1 className="text-lg font-semibold tracking-tight sm:text-xl">{title}</h1>
        {description && <p className="mt-0.5 hidden text-sm text-muted-foreground sm:block">{description}</p>}
      </div>
      <HealthPill />
    </div>
  );
}
