import { Suspense } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { ResumeWorkspace } from "@/components/resume/resume-workspace";

export default function ResumePage() {
  return (
    <AppShell activePath="/resume">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Resume</h1>
        <p className="mt-1 text-muted-foreground">
          Tailor your resume to any job description, then check its ATS score
        </p>
      </div>
      {/* The workspace reads ?run= from the URL, which needs a Suspense boundary on a static page */}
      <Suspense>
        <ResumeWorkspace />
      </Suspense>
    </AppShell>
  );
}
