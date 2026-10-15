"use client";

import { useEffect, useState } from "react";
import {
  Briefcase,
  Building2,
  Calendar,
  ExternalLink,
  Filter,
  FileText,
  MapPin,
  MessageSquare,
  Plus,
  Search,
  Sparkles,
  Trash2,
  TrendingUp,
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

export function JobTracker({ onOpenOutreach }: JobTrackerProps) {
  const [jobs, setJobs] = useState<JobApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [editingJob, setEditingJob] = useState<JobApplication | null>(null);

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
      console.error("Failed to load jobs", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
  }, []);

  const openAddModal = () => {
    setEditingJob(null);
    setCompany("");
    setJobTitle("");
    setJobUrl("");
    setLocation("");
    setSalary("");
    setStatus("saved");
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
      console.error("Failed to save job application", err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to remove this job application?")) return;
    try {
      await deleteJob(id);
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch (err) {
      console.error("Failed to delete job", err);
    }
  };

  const handleStatusChange = async (id: string, newStatus: JobStatus) => {
    try {
      const updated = await updateJob(id, { status: newStatus });
      setJobs((prev) => prev.map((j) => (j.id === id ? updated : j)));
    } catch (err) {
      console.error("Failed to update status", err);
    }
  };

  const filteredJobs = jobs.filter((j) => {
    if (filterStatus !== "all" && j.status !== filterStatus) return false;
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
  };

  return (
    <div className="space-y-6">
      {/* Top Banner / Summary Stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="text-xs font-medium text-muted-foreground">Total Tracked</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-bold">{stats.total}</span>
            <span className="text-xs text-muted-foreground">opportunities</span>
          </div>
        </div>
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="text-xs font-medium text-muted-foreground">Active Pipelines</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-primary">{stats.active}</span>
            <span className="text-xs text-muted-foreground">in progress</span>
          </div>
        </div>
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="text-xs font-medium text-muted-foreground">Interviews</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-amber-500">{stats.interviewing}</span>
            <span className="text-xs text-muted-foreground">active</span>
          </div>
        </div>
        <div className="rounded-xl border bg-card p-4 shadow-sm">
          <div className="text-xs font-medium text-muted-foreground">Offers</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-emerald-500">{stats.offers}</span>
            <span className="text-xs text-emerald-500/80">received</span>
          </div>
        </div>
      </div>

      {/* Control Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 items-center gap-2">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Filter company, role, location..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border bg-background pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="h-9 rounded-lg border bg-background px-2 text-xs font-medium"
            >
              <option value="all">All statuses</option>
              <option value="saved">Saved</option>
              <option value="applied">Applied</option>
              <option value="interviewing">Interviewing</option>
              <option value="offered">Offered</option>
              <option value="rejected">Rejected</option>
              <option value="archived">Archived</option>
            </select>
          </div>
        </div>

        <button
          onClick={openAddModal}
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground shadow hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-4 w-4" />
          Track New Job
        </button>
      </div>

      {/* Jobs List */}
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
              onClick={openAddModal}
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted"
            >
              <Plus className="h-3.5 w-3.5" />
              Add your first job
            </button>
          )}
        </div>
      ) : (
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

                    <select
                      value={job.status}
                      onChange={(e) => handleStatusChange(job.id, e.target.value as JobStatus)}
                      className={cn(
                        "rounded-full border px-2.5 py-0.5 text-xs font-semibold focus:outline-none transition-colors",
                        statusMeta.bg,
                        statusMeta.text,
                        statusMeta.border
                      )}
                    >
                      <option value="saved">Saved</option>
                      <option value="applied">Applied</option>
                      <option value="interviewing">Interviewing</option>
                      <option value="offered">Offered</option>
                      <option value="rejected">Rejected</option>
                      <option value="archived">Archived</option>
                    </select>
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
                    {onOpenOutreach && (
                      <button
                        onClick={() => onOpenOutreach(job)}
                        className="flex items-center gap-1 text-primary hover:underline font-medium"
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
                  <label className="block text-xs font-medium text-muted-foreground mb-1">
                    Status
                  </label>
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value as JobStatus)}
                    className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="saved">Saved</option>
                    <option value="applied">Applied</option>
                    <option value="interviewing">Interviewing</option>
                    <option value="offered">Offered</option>
                    <option value="rejected">Rejected</option>
                    <option value="archived">Archived</option>
                  </select>
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
    </div>
  );
}
