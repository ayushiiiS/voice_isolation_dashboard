"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { AuthGuard } from "@/components/layout/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { api, JobDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatDate, formatDuration, formatError } from "@/lib/utils";
import { ArrowLeft, RefreshCw } from "lucide-react";

function jobStatusBadge(job: JobDetail) {
  if (job.status === "completed" && job.failed_count > 0) {
    return { label: "completed with errors", variant: "warning" as const };
  }
  switch (job.status) {
    case "completed":
      return { label: "completed", variant: "success" as const };
    case "processing":
    case "queued":
      return { label: job.status, variant: "warning" as const };
    case "failed":
      return { label: "failed", variant: "destructive" as const };
    default:
      return { label: job.status, variant: "secondary" as const };
  }
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);

  const loadJob = useCallback(async () => {
    if (!token || !id) return;
    try {
      const data = await api.job(token, id);
      setJob(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load job");
    } finally {
      setLoading(false);
    }
  }, [token, id]);

  useEffect(() => {
    loadJob();
  }, [loadJob]);

  useEffect(() => {
    if (!token || !id || !job) return;
    const active =
      job.status === "processing" ||
      job.status === "queued" ||
      job.recordings.some((r) => r.status === "processing" || r.status === "queued");
    if (!active) return;

    const interval = setInterval(loadJob, 5000);
    return () => clearInterval(interval);
  }, [token, id, job, loadJob]);

  const handleRetry = async () => {
    if (!token || !id) return;
    setRetrying(true);
    try {
      const res = await api.retryJob(token, id);
      toast.success(`Retried ${res.retried} failed recording(s)`);
      await loadJob();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  };

  const badge = job ? jobStatusBadge(job) : null;

  return (
    <AuthGuard>
      <AppShell
        title="Job Details"
        actions={
          job && (
            <>
              <Button variant="outline" size="sm" onClick={() => loadJob()}>
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
              {job.failed_count > 0 && (
                <Button size="sm" onClick={handleRetry} disabled={retrying}>
                  <RefreshCw className={`h-4 w-4 ${retrying ? "animate-spin" : ""}`} />
                  Retry Failed
                </Button>
              )}
            </>
          )
        }
      >
        {loading || !job ? (
          <div className="flex h-64 items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        ) : (
          <div className="space-y-6">
            <Button variant="ghost" size="sm" asChild className="-ml-2 text-muted-foreground">
              <Link href="/dashboard">
                <ArrowLeft className="h-4 w-4" />
                Back to dashboard
              </Link>
            </Button>

            <Card className="border-border/60 bg-card/80">
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <CardTitle>{job.file_name || "Processing job"}</CardTitle>
                    <CardDescription className="mt-1 font-mono text-xs">
                      Job ID: {job.id}
                    </CardDescription>
                  </div>
                  {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="mb-2 flex justify-between text-sm">
                    <span className="text-muted-foreground">Overall progress</span>
                    <span className="font-medium">{Math.round((job.progress || 0) * 100)}%</span>
                  </div>
                  <Progress value={(job.progress || 0) * 100} />
                </div>
                <div className="flex flex-wrap gap-4 text-sm">
                  <span>
                    <span className="text-green-400">{job.completed_count}</span> completed
                  </span>
                  <span>
                    <span className="text-red-400">{job.failed_count}</span> failed
                  </span>
                  <span className="text-muted-foreground">
                    of {job.total_recordings} total
                  </span>
                  <span className="text-muted-foreground">· Created {formatDate(job.created_at)}</span>
                </div>
                {job.failed_count > 0 && job.status === "completed" && (
                  <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                    This job finished but some recordings failed. Use <strong>Retry Failed</strong> after
                    fixing permissions or URLs.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/60 bg-card/80">
              <CardHeader>
                <CardTitle>Recordings</CardTitle>
                <CardDescription>Status for each recording in this job.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-left text-muted-foreground">
                        <th className="pb-3 pr-4 font-medium">File</th>
                        <th className="pb-3 pr-4 font-medium">Status</th>
                        <th className="pb-3 pr-4 font-medium">Duration</th>
                        <th className="pb-3 font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {job.recordings.map((rec) => {
                        const errorMsg = formatError(rec.error);
                        return (
                          <tr key={rec.id} className="border-b border-border/50 align-top">
                            <td className="py-3 pr-4">
                              <p className="font-medium">{rec.file_name || rec.id.slice(-8)}</p>
                            </td>
                            <td className="py-3 pr-4">
                              <Badge
                                variant={
                                  rec.status === "completed"
                                    ? "success"
                                    : rec.status === "failed"
                                      ? "destructive"
                                      : "secondary"
                                }
                              >
                                {rec.status}
                              </Badge>
                              {errorMsg && rec.status === "failed" && (
                                <p
                                  className="mt-2 max-w-md text-xs leading-relaxed text-red-300"
                                  title={rec.error}
                                >
                                  {errorMsg}
                                </p>
                              )}
                            </td>
                            <td className="py-3 pr-4">
                              {rec.duration_seconds
                                ? formatDuration(rec.duration_seconds)
                                : "—"}
                            </td>
                            <td className="py-3">
                              {rec.status === "completed" ? (
                                <Link
                                  href={`/calls/${rec.id}`}
                                  className="text-primary hover:underline"
                                >
                                  View analytics
                                </Link>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </AppShell>
    </AuthGuard>
  );
}
