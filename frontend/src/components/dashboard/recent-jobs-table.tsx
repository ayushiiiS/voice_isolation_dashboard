"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Job } from "@/lib/api";
import { formatDate } from "@/lib/utils";

function jobStatusBadge(job: Job) {
  if (job.status === "completed" && (job.failed_count ?? 0) > 0) {
    return { label: "completed with errors", variant: "warning" as const };
  }
  switch (job.status) {
    case "completed":
      return { label: "completed", variant: "success" as const };
    case "processing":
      return { label: "processing", variant: "warning" as const };
    case "failed":
      return { label: "failed", variant: "destructive" as const };
    default:
      return { label: job.status, variant: "secondary" as const };
  }
}

export function RecentJobsTable({ jobs }: { jobs: Job[] }) {
  return (
    <Card className="surface-elevated border-border/50">
      <CardHeader>
        <CardTitle>Recent Jobs</CardTitle>
        <CardDescription>Background batch tasks — open for per-recording status.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="pb-3 pr-4 font-medium">Job</th>
                <th className="pb-3 pr-4 font-medium">File</th>
                <th className="pb-3 pr-4 font-medium">Status</th>
                <th className="pb-3 pr-4 font-medium">Progress</th>
                <th className="pb-3 pr-4 font-medium">Results</th>
                <th className="pb-3 pr-4 font-medium">Created</th>
                <th className="pb-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-muted-foreground">
                    No jobs yet.
                  </td>
                </tr>
              )}
              {jobs.map((job) => {
                const badge = jobStatusBadge(job);
                return (
                  <tr key={job.id} className="table-row-hover border-b border-border/30 transition-colors">
                    <td className="py-3 pr-4 font-mono text-xs">{job.id.slice(-8)}</td>
                    <td className="py-3 pr-4 max-w-[140px] truncate" title={job.file_name}>
                      {job.file_name || "—"}
                    </td>
                    <td className="py-3 pr-4">
                      <Badge variant={badge.variant}>{badge.label}</Badge>
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-2">
                        <Progress value={(job.progress || 0) * 100} className="w-20" />
                        <span className="text-xs text-muted-foreground">
                          {Math.round((job.progress || 0) * 100)}%
                        </span>
                      </div>
                    </td>
                    <td className="py-3 pr-4 text-xs text-muted-foreground">
                      <span className="text-green-400">{job.completed_count ?? 0} ok</span>
                      {" · "}
                      <span className="text-red-400">{job.failed_count ?? 0} failed</span>
                      {job.total_recordings ? ` / ${job.total_recordings}` : ""}
                    </td>
                    <td className="py-3 pr-4 text-muted-foreground whitespace-nowrap">
                      {formatDate(job.created_at)}
                    </td>
                    <td className="py-3">
                      <Link href={`/jobs/${job.id}`} className="text-primary hover:underline">
                        View
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
