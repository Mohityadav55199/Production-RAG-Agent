"use client";

import type { Annotated, BulletInfo, ResumeProfile } from "@/lib/api/resume";
import { cn } from "@/lib/utils";

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

function sameItem(a: string, b: string) {
  const x = norm(a);
  const y = norm(b);
  return x === y || (x.length >= 4 && y.length >= 4 && (x.includes(y) || y.includes(x)));
}

const MARK: Record<BulletInfo["status"] | "edited", { label: string; className: string }> = {
  original: { label: "same", className: "border-l-emerald-500/60" },
  reworded: { label: "reworded", className: "border-l-sky-500/70 bg-sky-500/5" },
  new: { label: "no source", className: "border-l-amber-500/70 bg-amber-500/5" },
  edited: { label: "edited", className: "border-l-muted-foreground/40" },
};

function Column({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      {children}
    </div>
  );
}

function Row({ label, left, right }: { label: string; left: React.ReactNode; right: React.ReactNode }) {
  return (
    <section className="space-y-2 border-t pt-4 first:border-t-0 first:pt-0">
      <h4 className="text-sm font-semibold">{label}</h4>
      <div className="grid gap-4 md:grid-cols-2">
        <Column title="Your library">{left}</Column>
        <Column title="Tailored draft">{right}</Column>
      </div>
    </section>
  );
}

function Bullets({ items, mark }: { items: string[]; mark?: (text: string) => keyof typeof MARK | "unused" }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">Nothing here.</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((b, i) => {
        const m = mark?.(b);
        return (
          <li
            key={i}
            className={cn(
              "rounded-r-md border-l-2 py-1 pl-2.5 pr-1 text-sm",
              m === "unused" ? "border-l-transparent text-muted-foreground line-through decoration-muted-foreground/40" : m ? MARK[m].className : "border-l-border"
            )}
          >
            {b}
            {m && m !== "unused" && m !== "original" && (
              <span className="ml-1.5 whitespace-nowrap text-[11px] text-muted-foreground">({MARK[m].label})</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Side by side: the user's own resume as it is in the library, and the tailored draft. */
export function CompareView({ library, draft, annotated }: { library: ResumeProfile; draft: ResumeProfile; annotated: Annotated | null }) {
  const statusOf = (bullets: BulletInfo[] | undefined) => (text: string) =>
    (bullets?.find((b) => b.text === text)?.status ?? "edited") as keyof typeof MARK;

  const libSkills = Object.values(library.skills).flat();
  const draftSkills = Object.values(draft.skills).flat();
  const inDraft = new Set(draftSkills.map(norm));
  const inLibrary = new Set(libSkills.map(norm));

  const roles = draft.experience.map((role) => ({
    role,
    lib: library.experience.find((r) => sameItem(r.company, role.company)),
    info: annotated?.experience.find((r) => r.company === role.company)?.bullets,
  }));
  const droppedRoles = library.experience.filter((r) => !draft.experience.some((d) => sameItem(d.company, r.company)));
  const projects = draft.projects.map((proj) => ({
    proj,
    lib: library.projects.find((p) => sameItem(p.name, proj.name)),
    info: annotated?.projects.find((p) => p.name === proj.name)?.bullets,
  }));
  const droppedProjects = library.projects.filter((p) => !draft.projects.some((d) => sameItem(d.name, p.name)));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="h-3 w-0.5 bg-sky-500" />Reworded from your library</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-0.5 bg-amber-500" />No library source</span>
        <span className="flex items-center gap-1.5"><span className="line-through">Struck out</span>: left out of the draft</span>
      </div>

      <Row
        label="Summary"
        left={<p className="text-sm">{library.summary || <span className="text-muted-foreground">No summary.</span>}</p>}
        right={<p className="text-sm">{draft.summary || <span className="text-muted-foreground">No summary.</span>}</p>}
      />

      <Row
        label="Skills"
        left={
          <div className="flex flex-wrap gap-1.5">
            {libSkills.map((s) => (
              <span key={s} className={cn("rounded-full border px-2 py-0.5 text-xs", !inDraft.has(norm(s)) && "text-muted-foreground line-through")}>{s}</span>
            ))}
          </div>
        }
        right={
          <div className="flex flex-wrap gap-1.5">
            {draftSkills.map((s) => (
              <span
                key={s}
                className={cn("rounded-full border px-2 py-0.5 text-xs", !inLibrary.has(norm(s)) && "border-amber-500/40 bg-amber-500/10")}
                title={inLibrary.has(norm(s)) ? undefined : "Not in your library"}
              >
                {s}
              </span>
            ))}
          </div>
        }
      />

      {roles.map(({ role, lib, info }, i) => (
        <Row
          key={`r-${i}`}
          label={`${role.company}${role.title ? ` · ${role.title}` : ""}`}
          left={lib ? <Bullets items={lib.bullets} mark={(b) => (role.bullets.includes(b) || info?.some((x) => x.source === b) ? "original" : "unused")} /> : <p className="text-sm text-amber-700 dark:text-amber-400">This role is not in your library.</p>}
          right={<Bullets items={role.bullets} mark={statusOf(info)} />}
        />
      ))}

      {projects.map(({ proj, lib, info }, i) => (
        <Row
          key={`p-${i}`}
          label={`Project: ${proj.name}`}
          left={lib ? <Bullets items={lib.bullets} mark={(b) => (proj.bullets.includes(b) || info?.some((x) => x.source === b) ? "original" : "unused")} /> : <p className="text-sm text-amber-700 dark:text-amber-400">This project is not in your library.</p>}
          right={<Bullets items={proj.bullets} mark={statusOf(info)} />}
        />
      ))}

      {(droppedRoles.length > 0 || droppedProjects.length > 0) && (
        <section className="space-y-1 border-t pt-4 text-sm">
          <h4 className="font-semibold">In your library, not in this draft</h4>
          <p className="text-muted-foreground">
            {[...droppedRoles.map((r) => r.company), ...droppedProjects.map((p) => p.name)].join(", ")}
          </p>
        </section>
      )}
    </div>
  );
}
