"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DashboardRecording } from "@/lib/api";
import { formatDate, formatDuration, formatError } from "@/lib/utils";
import { ExternalLink, Upload } from "lucide-react";

function statusVariant(status: string) {
  switch (status) {
    case "completed":
      return "success" as const;
    case "processing":
    case "queued":
      return "warning" as const;
    case "failed":
      return "destructive" as const;
    default:
      return "secondary" as const;
  }
}

function storageLabel(rec: DashboardRecording): {
  label: string;
  variant: "success" | "warning" | "destructive" | "secondary";
} {
  if (rec.storage_type === "gcs" && rec.upload_status === "success") {
    return { label: "GCS Stored", variant: "success" };
  }
  if (rec.status === "completed" && rec.upload_status === "failed") {
    return { label: "Local Only", variant: "warning" };
  }
  if (rec.upload_status === "failed" && rec.status === "failed") {
    return { label: "Not saved", variant: "secondary" };
  }
  return { label: "—", variant: "secondary" };
}

export function RecentRecordingsTable({ recordings }: { recordings: DashboardRecording[] }) {
  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div>
          <CardTitle>Processed Recordings</CardTitle>
          <CardDescription>
            Latest isolation results — open Details to hear separated audio and view analytics.
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/upload">
            <Upload className="h-4 w-4" />
            Upload
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        {recordings.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-12 text-center">
            <p className="mb-1 font-medium">No recordings yet</p>
            <p className="mb-4 max-w-sm text-sm text-muted-foreground">
              Upload a recording URL (https://, or gs://) to isolate user and agent audio.
            </p>
            <Button asChild>
              <Link href="/upload">Upload your first recording</Link>
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="pb-3 pr-4 font-medium">File</th>
                  <th className="pb-3 pr-4 font-medium">Status</th>
                  <th className="pb-3 pr-4 font-medium">Storage</th>
                  <th className="pb-3 pr-4 font-medium">Duration</th>
                  <th className="pb-3 pr-4 font-medium">Outputs</th>
                  <th className="pb-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {recordings.map((rec) => {
                  const storage = storageLabel(rec);
                  const errorMsg = formatError(rec.error || rec.gcs_error);
                  return (
                    <tr key={rec.id} className="border-b border-border/50 align-top">
                      <td className="py-3 pr-4">
                        <p className="font-medium">{rec.file_name || rec.id.slice(-8)}</p>
                        {rec.job_id && (
                          <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                            job …{rec.job_id.slice(-6)}
                          </p>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        <Badge variant={statusVariant(rec.status)}>{rec.status}</Badge>
                        {errorMsg && rec.status === "failed" && (
                          <p
                            className="mt-2 max-w-xs text-xs leading-relaxed text-red-300"
                            title={rec.error || rec.gcs_error}
                          >
                            {errorMsg}
                          </p>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        {rec.status === "completed" ? (
                          <Badge variant={storage.variant}>{storage.label}</Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-3 pr-4">
                        {rec.duration_seconds
                          ? formatDuration(rec.duration_seconds)
                          : "—"}
                      </td>
                      <td className="py-3 pr-4">
                        {rec.status === "completed" ? (
                          <div className="flex flex-col gap-1">
                            {rec.user_audio_url && (
                              <a
                                href={rec.user_audio_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                              >
                                User audio <ExternalLink className="h-3 w-3" />
                              </a>
                            )}
                            {rec.agent_audio_url && (
                              <a
                                href={rec.agent_audio_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:underline"
                              >
                                Agent audio <ExternalLink className="h-3 w-3" />
                              </a>
                            )}
                          </div>
                        ) : rec.job_id ? (
                          <Link
                            href={`/jobs/${rec.job_id}`}
                            className="text-xs text-primary hover:underline"
                          >
                            View job
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="py-3">
                        {rec.status === "completed" && (
                          <Link href={`/calls/${rec.id}`} className="text-primary hover:underline">
                            Details
                          </Link>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {recordings[0]?.updated_at && (
          <p className="mt-3 text-xs text-muted-foreground">
            Last updated: {formatDate(recordings[0].updated_at)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
