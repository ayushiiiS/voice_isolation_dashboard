"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DashboardStats } from "@/lib/api";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { AlertTriangle, Clock, Loader2, RefreshCw } from "lucide-react";

export function ActionCenter({
  stats,
  onRefresh,
}: {
  stats: DashboardStats;
  onRefresh: () => void;
}) {
  const { token } = useAuth();
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);

  const failed = stats.failed_recordings ?? 0;
  const queued = (stats.queued_recordings ?? 0) + (stats.queued_jobs ?? 0);
  const processing =
    (stats.processing_recordings ?? 0) + (stats.processing_jobs ?? 0);

  const hasActions = failed > 0 || queued > 0 || processing > 0;
  if (!hasActions) return null;

  const failedJobs = stats.recent_jobs.filter((j) => (j.failed_count ?? 0) > 0);

  const handleRetryAll = async () => {
    if (!token || failedJobs.length === 0) return;
    setRetrying(true);
    try {
      let total = 0;
      for (const job of failedJobs) {
        const res = await api.retryJob(token, job.id);
        total += res.retried;
      }
      toast.success(`Retried ${total} failed recording(s) across ${failedJobs.length} job(s)`);
      onRefresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  };

  const firstProcessingJob = stats.recent_jobs.find(
    (j) => j.status === "processing" || j.status === "queued",
  );

  return (
    <div className="surface-elevated rounded-xl p-5">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
        Action Required
      </h2>
      <div className="grid gap-3 sm:grid-cols-3">
        {failed > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-red-500/20 bg-red-500/5 p-4">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 shrink-0 text-red-400" />
              <div>
                <p className="font-medium text-red-100">{failed} Failed</p>
                <p className="text-xs text-muted-foreground">Recordings need attention</p>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="shrink-0 border-red-500/30 hover:bg-red-500/10"
              onClick={handleRetryAll}
              disabled={retrying || failedJobs.length === 0}
            >
              {retrying ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Retry All
            </Button>
          </div>
        )}

        {queued > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
            <div className="flex items-center gap-3">
              <Clock className="h-5 w-5 shrink-0 text-amber-400" />
              <div>
                <p className="font-medium text-amber-100">{queued} Queued</p>
                <p className="text-xs text-muted-foreground">Waiting to process</p>
              </div>
            </div>
            <Button size="sm" variant="outline" asChild>
              <Link href="/dashboard?tab=processing">View Queue</Link>
            </Button>
          </div>
        )}

        {processing > 0 && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-4">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-indigo-400" />
              <div>
                <p className="font-medium text-indigo-100">{processing} Processing</p>
                <p className="text-xs text-muted-foreground">Active jobs running</p>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (firstProcessingJob) {
                  router.push(`/jobs/${firstProcessingJob.id}`);
                } else {
                  router.push("/dashboard?tab=processing");
                }
              }}
            >
              Monitor
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
