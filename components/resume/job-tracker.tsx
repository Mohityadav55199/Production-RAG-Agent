"use client";

import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Briefcase,
  Building2,
  Calendar,
  ExternalLink,
  Filter,
  FileText,
  GripVertical,
  Kanban,
  LayoutGrid,
  MapPin,
  MessageSquare,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import {
  createJob,
  deleteJob,
  listJobs,
  updateJob,
  type JobApplication,
  type JobStatus,
} from "@/lib/api/resume";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { Select } from "@/components/ui/select";

const STATUS_CONFIG: Record<
  JobStatus,
  { label: string; bg: string; text: string; border: string }
> = {
  saved: {
    label: "Saved",
    bg: "bg-muted",
    text: "text-muted-foreground",
    border: "border-muted-foreground/20",
  },
  applied: {
    label: "Applied",
    bg: "bg-blue-500/10",
    text: "text-blue-500",
    border: "border-blue-500/30",
  },
  interviewing: {
    label: "Interviewing",
    bg: "bg-amber-500/10",
    text: "text-amber-500",
    border: "border-amber-500/30",
  },
  offered: {
    label: "Offered",
    bg: "bg-emerald-500/10",
    text: "text-emerald-500",
    border: "border-emerald-500/30",
  },
  rejected: {
    label: "Rejected",
    bg: "bg-red-500/10",
    text: "text-red-500",
    border: "border-red-500/30",
  },
  archived: {
    label: "Archived",
    bg: "bg-zinc-500/10",
    text: "text-zinc-500",
    border: "border-zinc-500/30",
  },
};

interface JobTrackerProps {
  onOpenOutreach?: (job: JobApplication) => void;
}


const STATUS_OPTIONS = (Object.keys(STATUS_CONFIG) as JobStatus[]).map((value) => ({ value, label: STATUS_CONFIG[value].label }));
const FILTER_OPTIONS = [{ value: "all", label: "All statuses" }, ...STATUS_OPTIONS];

export function JobTracker({ onOpenOutreach }: JobTrackerProps) {
  const { confirm, dialog } = useConfirm();
  const [jobs, setJobs] = useState<JobApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [editingJob, setEditingJob] = useState<JobApplication | null>(null);

  const [viewMode, setViewMode] = useState<"kanban" | "list">("kanban");
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  // Form states
  const [company, setCompany] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [jobUrl, setJobUrl] = useState("");
  const [location, setLocation] = useState("");
  const [salary, setSalary] = useState("");
  const [status, setStatus] = useState<JobStatus>("saved");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchJobs = async () => {
    try {
      setLoading(true);
      const data = await listJobs();
      setJobs(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load your jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    listJobs()
      .then((data) => !cancelled && setJobs(data))
      .catch((err) => !cancelled && toast.error(err instanceof Error ? err.message : "Could not load your jobs"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const openAddModal = (defaultStatus: JobStatus = "saved") => {
    setEditingJob(null);
    setCompany("");
    setJobTitle("");
    setJobUrl("");
    setLocation("");
    setSalary("");
    setStatus(defaultStatus);
    setNotes("");
    setShowModal(true);
  };

  const openEditModal = (job: JobApplication) => {
    setEditingJob(job);
    setCompany(job.company);
    setJobTitle(job.job_title);
    setJobUrl(job.job_url || "");
    setLocation(job.location || "");
    setSalary(job.salary || "");
    setStatus(job.status);
    setNotes(job.notes || "");
    setShowModal(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!company.trim() || !jobTitle.trim()) return;
    setSaving(true);
    try {
      if (editingJob) {
        await updateJob(editingJob.id, {
          company,
          job_title: jobTitle,
          job_url: jobUrl || null,
          location: location || null,
          salary: salary || null,
          status,
          notes: notes || null,
        });
      } else {
        await createJob({
          company,
          job_title: jobTitle,
          job_url: jobUrl || null,
          location: location || null,
          salary: salary || null,
          status,
          notes: notes || null,
        });
      }
      setShowModal(false);
      await fetchJobs();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save the job");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm({ title: "Remove this job application?", confirmLabel: "Remove" });
    if (!ok) return;
    try {
      await deleteJob(id);
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not remove the job");
    }
  };

  const handleStatusChange = async (id: string, newStatus: JobStatus) => {
    try {
      const updated = await updateJob(id, { status: newStatus });
      setJobs((prev) => prev.map((j) => (j.id === id ? updated : j)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not update the status");
    }
  };

  const filteredJobs = jobs.filter((j) => {
    if (viewMode === "list" && filterStatus !== "all" && j.status !== filterStatus) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        j.company.toLowerCase().includes(q) ||
        j.job_title.toLowerCase().includes(q) ||
        (j.location && j.location.toLowerCase().includes(q)) ||
        (j.notes && j.notes.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const stats = {
    total: jobs.length,
    active: jobs.filter((j) => ["applied", "interviewing", "offered"].includes(j.status)).length,
    interviewing: jobs.filter((j) => j.status === "interviewing").length,
    offers: jobs.filter((j) => j.status === "offered").length,
    archived: jobs.filter((j) => ["rejected", "archived"].includes(j.status)).length,
  };

  const KANBAN_STAGES: { status: JobStatus; label: string; bg: string; text: string; border: string; desc: string }[] = [
    { status: "saved", label: "Saved", bg: "bg-muted", text: "text-muted-foreground", border: "border-muted-foreground/30", desc: "Bookmarked roles" },
    { status: "applied", label: "Applied", bg: "bg-blue-500/10", text: "text-blue-600 dark:text-blue-400", border: "border-blue-500/30", desc: "Submitted" },
    { status: "interviewing", label: "Interviewing", bg: "bg-amber-500/10", text: "text-amber-600 dark:text-amber-400", border: "border-amber-500/30", desc: "In discussions" },
    { status: "offered", label: "Offered", bg: "bg-emerald-500/10", text: "text-emerald-600 dark:text-emerald-400", border: "border-emerald-500/30", desc: "Offers received" },
  ];

  return (
    <div className="space-y-6">
      {/* Summary: one slim row */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-xl border bg-card px-4 py-2.5 text-sm">
        {[
          { label: "tracked", value: stats.total, color: "" },
          { label: "in progress", value: stats.active, color: "text-primary" },
          { label: "interviewing", value: stats.interviewing, color: "text-amber-600 dark:text-amber-400" },
          { label: stats.offers === 1 ? "offer" : "offers", value: stats.offers, color: "text-emerald-600 dark:text-emerald-400" },
        ].map((s) => (
          <span key={s.label} className="flex items-baseline gap-1.5">
            <strong className={cn("text-lg font-semibold tabular-nums", s.color)}>{s.value}</strong>
            <span className="text-muted-foreground">{s.label}</span>
          </span>
        ))}
      </div>

      {/* Control Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap flex-1 items-center gap-2">
          <div className="relative flex-1 min-w-[180px] max-w-sm">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search company, role, location..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border bg-background pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>

          {/* View Mode Toggle: Kanban vs List */}
          <div className="flex items-center rounded-lg border bg-muted/40 p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("kanban")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all",
                viewMode === "kanban" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Kanban className="size-3.5" />
              Kanban
            </button>
            <button
              type="button"
              onClick={() => setViewMode("list")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all",
                viewMode === "list" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <LayoutGrid className="size-3.5" />
              List
            </button>
          </div>

          {viewMode === "list" && (
            <div className="flex items-center gap-1.5">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <Select label="Filter by status" className="w-36" value={filterStatus} options={FILTER_OPTIONS} onChange={setFilterStatus} />
            </div>
          )}
        </div>

        <button
          onClick={() => openAddModal("saved")}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 transition-colors shrink-0"
        >
          <Plus className="h-4 w-4" />
          Track New Job
        </button>
      </div>

      {/* Main Content */}
      {loading ? (
        <div className="rounded-xl border border-dashed p-12 text-center text-sm text-muted-foreground">
          Loading your job tracker...
        </div>
      ) : filteredJobs.length === 0 ? (
        <div className="rounded-xl border border-dashed p-12 text-center">
          <Briefcase className="mx-auto h-8 w-8 text-muted-foreground/50" />
          <h3 className="mt-3 text-sm font-semibold">No job applications found</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {jobs.length === 0
              ? "Track roles you've saved or applied to, along with resume versions and tailored scores."
              : "No jobs match your current filter."}
          </p>
          {jobs.length === 0 && (
            <button
              onClick={() => openAddModal("saved")}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted"
            >
              <Plus className="h-3.5 w-3.5" />
              Add your first job
            </button>
          )}
        </div>
      ) : viewMode === "kanban" ? (
        /* Kanban Board View */
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 items-start">
            {KANBAN_STAGES.map((stage) => {
              const stageJobs = filteredJobs.filter((j) => j.status === stage.status);
              const isOver = dragOverCol === stage.status;
              return (
                <div
                  key={stage.status}
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (dragOverCol !== stage.status) setDragOverCol(stage.status);
                  }}
                  onDragLeave={() => {
                    if (dragOverCol === stage.status) setDragOverCol(null);
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOverCol(null);
                    const id = e.dataTransfer.getData("text/plain");
                    if (id) handleStatusChange(id, stage.status);
                  }}
                  className={cn(
                    "flex flex-col rounded-xl border bg-card/60 backdrop-blur-sm p-3 transition-colors min-h-[460px]",
                    isOver ? "border-primary bg-primary/5 ring-2 ring-primary/20" : "border-border"
                  )}
                >
                  {/* Column Header */}
                  <div className="flex items-center justify-between gap-2 pb-3 mb-2 border-b">
                    <div className="flex items-center gap-2">
                      <span className={cn("size-2 rounded-full", stage.bg.replace("/10", ""))} />
                      <h4 className="font-semibold text-sm">{stage.label}</h4>
                      <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-semibold tabular-nums text-muted-foreground">
                        {stageJobs.length}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => openAddModal(stage.status)}
                      className="size-6 rounded-md hover:bg-muted flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
                      title={`Add job to ${stage.label}`}
                    >
                      <Plus className="size-3.5" />
                    </button>
                  </div>

                  {/* Cards in this stage */}
                  <div className="flex flex-col gap-2.5 flex-1">
                    {stageJobs.length === 0 ? (
                      <div className="flex-1 flex flex-col items-center justify-center rounded-lg border border-dashed border-muted/80 p-6 text-center text-xs text-muted-foreground/70">
                        <span>No jobs in {stage.label}</span>
                        <span className="text-[11px] mt-0.5">Drag cards here or click +</span>
                      </div>
                    ) : (
                      stageJobs.map((job) => (
                        <div
                          key={job.id}
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData("text/plain", job.id);
                            e.dataTransfer.effectAllowed = "move";
                          }}
                          className="group relative rounded-lg border bg-card p-3 shadow-xs transition-all hover:border-primary/50 hover:shadow-sm cursor-grab active:cursor-grabbing"
                        >
                          <div className="flex items-start justify-between gap-1.5">
                            <div className="min-w-0 flex-1">
                              <h5 className="font-semibold text-sm leading-snug line-clamp-1">{job.job_title}</h5>
                              <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                                <Building2 className="size-3 shrink-0" />
                                <span className="truncate">{job.company}</span>
                                {job.job_url && (
                                  <a
                                    href={job.job_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-muted-foreground/60 hover:text-primary"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <ExternalLink className="size-2.5" />
                                  </a>
                                )}
                              </div>
                            </div>
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                              <GripVertical className="size-3.5 text-muted-foreground/40" />
                            </div>
                          </div>

                          {/* Metadata row */}
                          <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-muted-foreground">
                            {job.location && (
                              <span className="flex items-center gap-1">
                                <MapPin className="size-2.5 shrink-0" />
                                <span className="truncate max-w-[120px]">{job.location}</span>
                              </span>
                            )}
                            {job.salary && (
                              <span className="font-medium text-foreground/80">{job.salary}</span>
                            )}
                            {job.applied_date && stage.status !== "saved" && (
                              <span className="flex items-center gap-1 text-[10px]">
                                <Calendar className="size-2.5 shrink-0" />
                                {new Date(job.applied_date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                              </span>
                            )}
                          </div>

                          {/* Resume tag & ATS */}
                          {(job.resume_version_name || job.ats_score !== null) && (
                            <div className="mt-2 flex items-center justify-between rounded bg-muted/50 px-2 py-1 text-[11px]">
                              <span className="flex items-center gap-1 truncate text-muted-foreground">
                                <FileText className="size-3 text-primary shrink-0" />
                                <span className="truncate max-w-[130px]">{job.resume_version_name || "Tailored"}</span>
                              </span>
                              {job.ats_score !== null && (
                                <span className="rounded bg-primary/10 px-1 font-semibold text-primary text-[10px]">
                                  {job.ats_score}%
                                </span>
                              )}
                            </div>
                          )}

                          {job.notes && (
                            <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground italic bg-muted/20 rounded p-1.5">
                              &ldquo;{job.notes}&rdquo;
                            </p>
                          )}

                          {/* Quick stage progression & actions */}
                          <div className="mt-2.5 pt-2 border-t flex items-center justify-between text-xs">
                            <div className="flex items-center gap-1.5">
                              {stage.status === "saved" && (
                                <button
                                  type="button"
                                  onClick={() => handleStatusChange(job.id, "applied")}
                                  className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-2 py-0.5 text-[11px] font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-500/20 transition-colors"
                                  title="Mark as Applied"
                                >
                                  Applied <ArrowRight className="size-2.5" />
                                </button>
                              )}
                              {stage.status === "applied" && (
                                <>
                                  <button
                                    type="button"
                                    onClick={() => handleStatusChange(job.id, "saved")}
                                    className="text-[10px] text-muted-foreground hover:text-foreground"
                                    title="Move back to Saved"
                                  >
                                    <ArrowLeft className="size-2.5 inline mr-0.5" />Saved
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => handleStatusChange(job.id, "interviewing")}
                                    className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-600 dark:text-amber-400 hover:bg-amber-500/20 transition-colors"
                                    title="Move to Interviewing"
                                  >
                                    Interview <ArrowRight className="size-2.5" />
                                  </button>
                                </>
                              )}
                              {stage.status === "interviewing" && (
                                <>
                                  <button
                                    type="button"
                                    onClick={() => handleStatusChange(job.id, "applied")}
                                    className="text-[10px] text-muted-foreground hover:text-foreground"
                                    title="Move back to Applied"
                                  >
                                    <ArrowLeft className="size-2.5 inline mr-0.5" />Applied
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => handleStatusChange(job.id, "offered")}
                                    className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/20 transition-colors"
                                    title="Mark as Offered"
                                  >
                                    Offered <ArrowRight className="size-2.5" />
                                  </button>
                                </>
                              )}
                              {stage.status === "offered" && (
                                <button
                                  type="button"
                                  onClick={() => handleStatusChange(job.id, "interviewing")}
                                  className="text-[10px] text-muted-foreground hover:text-foreground"
                                  title="Move back to Interviewing"
                                >
                                  <ArrowLeft className="size-2.5 inline mr-0.5" />Interviewing
                                </button>
                              )}
                            </div>

                            <div className="flex items-center gap-1.5 shrink-0">
                              {onOpenOutreach && job.resume_generation_id && (
                                <button
                                  type="button"
                                  onClick={() => onOpenOutreach(job)}
                                  className="text-primary hover:text-primary/80"
                                  title="Outreach messages"
                                >
                                  <MessageSquare className="size-3" />
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => openEditModal(job)}
                                className="text-muted-foreground hover:text-foreground text-[11px] font-medium"
                              >
                                Edit
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDelete(job.id)}
                                className="text-muted-foreground/50 hover:text-destructive"
                                title="Delete job"
                              >
                                <Trash2 className="size-3" />
                              </button>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Archived / Closed toggle if any exist */}
          {stats.archived > 0 && (
            <div className="pt-2">
              <button
                type="button"
                onClick={() => setShowArchived((v) => !v)}
                className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1.5"
              >
                <span>{showArchived ? "Hide" : "Show"} archived & rejected ({stats.archived})</span>
              </button>
              {showArchived && (
                <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {filteredJobs
                    .filter((j) => ["rejected", "archived"].includes(j.status))
                    .map((job) => {
                      const statusMeta = STATUS_CONFIG[job.status] || STATUS_CONFIG.archived;
                      return (
                        <div key={job.id} className="rounded-xl border bg-card/60 p-3.5 text-xs opacity-75">
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="font-semibold text-sm">{job.job_title}</p>
                              <p className="text-muted-foreground">{job.company}</p>
                            </div>
                            <Select
                              label="Status"
                              size="sm"
                              value={job.status}
                              options={STATUS_OPTIONS}
                              onChange={(next) => handleStatusChange(job.id, next)}
                              buttonClassName={cn("rounded-full font-semibold", statusMeta.bg, statusMeta.text, statusMeta.border)}
                            />
                          </div>
                        </div>
                      );
                    })}
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* List / Grid View */
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredJobs.map((job) => {
            const statusMeta = STATUS_CONFIG[job.status] || STATUS_CONFIG.saved;
            return (
              <div
                key={job.id}
                className="group relative flex flex-col justify-between rounded-xl border bg-card p-4.5 shadow-sm transition-all hover:border-primary/40 hover:shadow-md"
              >
                <div>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h4 className="font-semibold text-base leading-tight truncate">
                        {job.job_title}
                      </h4>
                      <div className="mt-1 flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                        <Building2 className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate">{job.company}</span>
                        {job.job_url && (
                          <a
                            href={job.job_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-muted-foreground/70 hover:text-primary"
                          >
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                    </div>

                    <Select
                      label="Status"
                      size="sm"
                      className="shrink-0"
                      value={job.status}
                      options={STATUS_OPTIONS}
                      onChange={(next) => handleStatusChange(job.id, next)}
                      buttonClassName={cn("rounded-full font-semibold", statusMeta.bg, statusMeta.text, statusMeta.border)}
                    />
                  </div>

                  <div className="mt-3 flex flex-wrap gap-y-1 gap-x-3 text-xs text-muted-foreground">
                    {job.location && (
                      <span className="flex items-center gap-1">
                        <MapPin className="h-3 w-3" />
                        {job.location}
                      </span>
                    )}
                    {job.salary && (
                      <span className="flex items-center gap-1 font-medium text-foreground/80">
                        {job.salary}
                      </span>
                    )}
                    {job.applied_date && (
                      <span className="flex items-center gap-1">
                        <Calendar className="h-3 w-3" />
                        Applied {new Date(job.applied_date).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  {/* Tailored resume badge if attached */}
                  {(job.resume_version_name || job.ats_score !== null) && (
                    <div className="mt-3 flex items-center justify-between rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs">
                      <span className="flex items-center gap-1.5 truncate text-muted-foreground">
                        <FileText className="h-3.5 w-3.5 text-primary" />
                        <span className="truncate">{job.resume_version_name || "Tailored Resume"}</span>
                      </span>
                      {job.ats_score !== null && (
                        <span className="rounded bg-primary/10 px-1.5 py-0.5 font-semibold text-primary">
                          {job.ats_score}% ATS
                        </span>
                      )}
                    </div>
                  )}

                  {job.notes && (
                    <p className="mt-2.5 line-clamp-2 text-xs text-muted-foreground italic">
                      &ldquo;{job.notes}&rdquo;
                    </p>
                  )}
                </div>

                <div className="mt-4 flex items-center justify-between border-t pt-2.5 text-xs">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openEditModal(job)}
                      className="text-muted-foreground hover:text-foreground font-medium"
                    >
                      Edit
                    </button>
                    {onOpenOutreach && job.resume_generation_id && (
                      <button
                        onClick={() => onOpenOutreach(job)}
                        className="flex items-center gap-1 text-primary hover:underline font-medium"
                        title="Open the tailored resume with its cover letter and recruiter message"
                      >
                        <MessageSquare className="h-3 w-3" />
                        Outreach
                      </button>
                    )}
                  </div>

                  <button
                    onClick={() => handleDelete(job.id)}
                    className="text-muted-foreground/60 hover:text-red-500"
                    title="Delete job"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border bg-card p-6 shadow-xl animate-in fade-in-50 zoom-in-95">
            <h3 className="text-lg font-semibold">
              {editingJob ? "Edit Job Application" : "Track a Job Opportunity"}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Keep your job hunt organized with status, resume versions, and notes.
            </p>

            <form onSubmit={handleSave} className="mt-4 space-y-3.5">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Company *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Corp"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Job Title *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Senior Full-Stack Engineer"
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <span className="block text-xs font-medium text-muted-foreground mb-1">
                    Status
                  </span>
                  <Select label="Status" className="w-full" value={status} options={STATUS_OPTIONS} onChange={setStatus} />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">
                    Salary / Compensation
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. $140k - $160k"
                    value={salary}
                    onChange={(e) => setSalary(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">
                    Location
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Remote / New York"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">
                    Job Posting URL
                  </label>
                  <input
                    type="url"
                    placeholder="https://..."
                    value={jobUrl}
                    onChange={(e) => setJobUrl(e.target.value)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Notes
                </label>
                <textarea
                  rows={2}
                  placeholder="Referral contact, key conversation points, tech stack notes..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                />
              </div>

              <div className="mt-5 flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="rounded-lg border px-4 py-2 text-sm font-medium hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {saving ? "Saving..." : editingJob ? "Update Job" : "Save Job"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {dialog}
    </div>
  );
}
