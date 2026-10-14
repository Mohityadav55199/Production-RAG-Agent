import { FileUser } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";

export default function ResumePage() {
  return (
    <AppShell activePath="/resume">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Resume</h1>
        <p className="mt-1 text-muted-foreground">
          Tailor your resume to any job description and check its ATS score
        </p>
      </div>
      <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed py-20 text-center">
        <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <FileUser className="size-7" />
        </div>
        <p className="font-medium">Coming soon</p>
        <p className="max-w-md text-sm text-muted-foreground">
          The resume library, ATS checker and tailoring agent are being built next.
        </p>
      </div>
    </AppShell>
  );
}
