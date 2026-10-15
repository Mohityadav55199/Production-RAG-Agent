import { Suspense } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { ResumeWorkspace } from "@/components/resume/resume-workspace";
import { PageHeader } from "@/components/layout/page-header";

export default function ResumePage() {
  return (
    <AppShell activePath="/resume">
      <PageHeader title="Resume" description="Tailor your resume to any job description, then check its ATS score" />
      {/* The workspace reads ?run= from the URL, which needs a Suspense boundary on a static page */}
      <Suspense>
        <ResumeWorkspace />
      </Suspense>
    </AppShell>
  );
}
