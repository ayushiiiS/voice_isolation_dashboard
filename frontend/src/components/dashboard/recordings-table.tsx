"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DashboardRecording } from "@/lib/api";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn, formatDate, formatDuration, formatError } from "@/lib/utils";
import {
  ArrowDown,
  ArrowUp,
  BarChart3,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  Headphones,
  Radio,
  RefreshCw,
  Search,
  Upload,
  XCircle,
} from "lucide-react";

type TabFilter = "all" | "failed" | "processing" | "completed";
type SortKey = "name" | "status" | "duration" | "uploaded" | "confidence";
type SortDir = "asc" | "desc";

const PAGE_SIZE = 8;

function statusConfig(status: string) {
  switch (status) {
    case "completed":
      return { variant: "success" as const, icon: CheckCircle2, label: "Completed" };
    case "processing":
      return { variant: "warning" as const, icon: Clock, label: "Processing" };
    case "queued":
      return { variant: "secondary" as const, icon: Clock, label: "Queued" };
    case "failed":
      return { variant: "destructive" as const, icon: XCircle, label: "Failed" };
    default:
      return { variant: "secondary" as const, icon: Clock, label: status };
  }
}

function storageLabel(rec: DashboardRecording) {
  if (rec.storage_type === "gcs" && rec.upload_status === "success") {
    return { label: "GCS", variant: "success" as const };
  }
  if (rec.status === "completed" && rec.upload_status === "failed") {
    return { label: "Local", variant: "warning" as const };
  }
  return { label: "—", variant: "secondary" as const };
}

function filterByTab(recordings: DashboardRecording[], tab: TabFilter) {
  if (tab === "all") return recordings;
  if (tab === "processing") {
    return recordings.filter((r) => r.status === "processing" || r.status === "queued");
  }
  return recordings.filter((r) => r.status === tab);
}

function tabCount(recordings: DashboardRecording[], tab: TabFilter) {
  return filterByTab(recordings, tab).length;
}

export function RecordingsTable({
  recordings,
  defaultTab = "all",
  onRetryJob,
}: {
  recordings: DashboardRecording[];
  defaultTab?: TabFilter;
  onRetryJob?: (jobId: string) => void;
}) {
  const { token } = useAuth();
  const [tab, setTab] = useState<TabFilter>(defaultTab);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("uploaded");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    let rows = filterByTab(recordings, tab);
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (r) =>
          (r.file_name || "").toLowerCase().includes(q) ||
          r.id.toLowerCase().includes(q) ||
          (r.job_id || "").toLowerCase().includes(q),
      );
    }
    rows = [...rows].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name":
          cmp = (a.file_name || a.id).localeCompare(b.file_name || b.id);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "duration":
          cmp = (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0);
          break;
        case "confidence":
          cmp = (a.avg_user_confidence ?? 0) - (b.avg_user_confidence ?? 0);
          break;
        case "uploaded":
        default:
          cmp =
            new Date(a.updated_at || a.created_at || 0).getTime() -
            new Date(b.updated_at || b.created_at || 0).getTime();
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [recordings, tab, search, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setPage(0);
  };

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (sortKey !== column) return null;
    return sortDir === "asc" ? (
      <ArrowUp className="ml-1 inline h-3 w-3" />
    ) : (
      <ArrowDown className="ml-1 inline h-3 w-3" />
    );
  };

  const handleRetry = async (jobId: string) => {
    if (!token) return;
    try {
      const res = await api.retryJob(token, jobId);
      toast.success(`Retried ${res.retried} recording(s)`);
      onRetryJob?.(jobId);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed");
    }
  };

  return (
    <Card className="surface-elevated border-border/50">
      <CardHeader className="space-y-4 pb-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="text-lg">Recordings</CardTitle>
            <CardDescription>
              Monitor processing status, confidence scores, and outputs.
            </CardDescription>
          </div>
          <Button size="sm" asChild>
            <Link href="/upload">
              <Upload className="h-4 w-4" />
              Upload
            </Link>
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as TabFilter);
            setPage(0);
          }}
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <TabsList className="h-auto flex-wrap justify-start bg-muted/50 p-1">
              <TabsTrigger value="all" className="gap-1.5">
                All
                <span className="rounded bg-background/60 px-1.5 text-xs tabular-nums">
                  {tabCount(recordings, "all")}
                </span>
              </TabsTrigger>
              <TabsTrigger value="failed" className="gap-1.5">
                Failed
                <span className="rounded bg-red-500/15 px-1.5 text-xs text-red-400 tabular-nums">
                  {tabCount(recordings, "failed")}
                </span>
              </TabsTrigger>
              <TabsTrigger value="processing" className="gap-1.5">
                Processing
                <span className="rounded bg-amber-500/15 px-1.5 text-xs text-amber-400 tabular-nums">
                  {tabCount(recordings, "processing")}
                </span>
              </TabsTrigger>
              <TabsTrigger value="completed" className="gap-1.5">
                Completed
                <span className="rounded bg-emerald-500/15 px-1.5 text-xs text-emerald-400 tabular-nums">
                  {tabCount(recordings, "completed")}
                </span>
              </TabsTrigger>
            </TabsList>

            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search recordings…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(0);
                }}
                className="pl-9 bg-muted/30"
              />
            </div>
          </div>

          {(["all", "failed", "processing", "completed"] as TabFilter[]).map((t) => (
            <TabsContent key={t} value={t} className="mt-4">
              {filtered.length === 0 ? (
                <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 py-16 text-center">
                  <p className="font-medium">No recordings in this view</p>
                  <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                    {t === "failed"
                      ? "No failed recordings — system is healthy."
                      : "Upload a recording URL or CSV batch to get started."}
                  </p>
                  {t !== "failed" && (
                    <Button className="mt-4" asChild>
                      <Link href="/upload">Upload recording</Link>
                    </Button>
                  )}
                </div>
              ) : (
                <>
                  <div className="overflow-x-auto rounded-lg border border-border/40">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border/60 bg-muted/20 text-left text-xs uppercase tracking-wide text-muted-foreground">
                          <th className="px-4 py-3 font-medium">
                            <button type="button" onClick={() => toggleSort("name")}>
                              Recording
                              <SortIcon column="name" />
                            </button>
                          </th>
                          <th className="px-4 py-3 font-medium">
                            <button type="button" onClick={() => toggleSort("status")}>
                              Status
                              <SortIcon column="status" />
                            </button>
                          </th>
                          <th className="px-4 py-3 font-medium">
                            <button type="button" onClick={() => toggleSort("duration")}>
                              Duration
                              <SortIcon column="duration" />
                            </button>
                          </th>
                          <th className="px-4 py-3 font-medium">
                            <button type="button" onClick={() => toggleSort("uploaded")}>
                              Upload Time
                              <SortIcon column="uploaded" />
                            </button>
                          </th>
                          <th className="px-4 py-3 font-medium">
                            <button type="button" onClick={() => toggleSort("confidence")}>
                              Confidence
                              <SortIcon column="confidence" />
                            </button>
                          </th>
                          <th className="px-4 py-3 font-medium">Storage</th>
                          <th className="px-4 py-3 font-medium text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {paged.map((rec) => {
                          const st = statusConfig(rec.status);
                          const StatusIcon = st.icon;
                          const storage = storageLabel(rec);
                          const errorMsg = formatError(rec.error || rec.gcs_error);
                          const confidence =
                            rec.avg_user_confidence != null
                              ? `${(rec.avg_user_confidence * 100).toFixed(0)}%`
                              : "—";

                          return (
                            <tr
                              key={rec.id}
                              className="table-row-hover border-b border-border/30 transition-colors"
                            >
                              <td className="px-4 py-4">
                                <p className="font-medium">{rec.file_name || rec.id.slice(-8)}</p>
                                {rec.job_id && (
                                  <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                                    job …{rec.job_id.slice(-6)}
                                  </p>
                                )}
                              </td>
                              <td className="px-4 py-4 align-top">
                                <Badge variant={st.variant} className="gap-1">
                                  <StatusIcon className="h-3 w-3" />
                                  {st.label}
                                </Badge>
                                {errorMsg && rec.status === "failed" && (
                                  <p
                                    className="mt-2 max-w-xs text-xs leading-relaxed text-red-300/90"
                                    title={rec.error || rec.gcs_error}
                                  >
                                    {errorMsg}
                                  </p>
                                )}
                              </td>
                              <td className="px-4 py-4 tabular-nums text-muted-foreground">
                                {rec.duration_seconds
                                  ? formatDuration(rec.duration_seconds)
                                  : "—"}
                              </td>
                              <td className="px-4 py-4 whitespace-nowrap text-muted-foreground">
                                {formatDate(rec.updated_at || rec.created_at)}
                              </td>
                              <td className="px-4 py-4">
                                {confidence !== "—" ? (
                                  <span
                                    className={cn(
                                      "tabular-nums font-medium",
                                      rec.avg_user_confidence! >= 0.8
                                        ? "text-emerald-400"
                                        : rec.avg_user_confidence! >= 0.6
                                          ? "text-amber-400"
                                          : "text-red-400",
                                    )}
                                  >
                                    {confidence}
                                  </span>
                                ) : (
                                  "—"
                                )}
                              </td>
                              <td className="px-4 py-4">
                                {rec.status === "completed" ? (
                                  <Badge variant={storage.variant}>{storage.label}</Badge>
                                ) : (
                                  "—"
                                )}
                              </td>
                              <td className="px-4 py-4">
                                <div className="flex items-center justify-end gap-1">
                                  {rec.status === "completed" && (
                                    <>
                                      <Button variant="ghost" size="sm" asChild title="Analytics">
                                        <Link href={`/calls/${rec.id}`}>
                                          <BarChart3 className="h-4 w-4" />
                                        </Link>
                                      </Button>
                                      {rec.user_audio_url && (
                                        <Button variant="ghost" size="sm" asChild title="Listen">
                                          <a
                                            href={rec.user_audio_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                          >
                                            <Headphones className="h-4 w-4" />
                                          </a>
                                        </Button>
                                      )}
                                      {rec.user_audio_url && (
                                        <Button variant="ghost" size="sm" asChild title="STT Comparison">
                                          <Link href={`/stt-comparison?recordingId=${rec.id}`}>
                                            <Radio className="h-4 w-4" />
                                          </Link>
                                        </Button>
                                      )}
                                      {rec.user_audio_url && (
                                        <Button variant="ghost" size="sm" asChild title="Download">
                                          <a href={rec.user_audio_url} download>
                                            <Download className="h-4 w-4" />
                                          </a>
                                        </Button>
                                      )}
                                    </>
                                  )}
                                  {rec.status === "failed" && rec.job_id && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      title="Retry"
                                      onClick={() => handleRetry(rec.job_id!)}
                                    >
                                      <RefreshCw className="h-4 w-4" />
                                    </Button>
                                  )}
                                  {rec.job_id && rec.status !== "completed" && (
                                    <Button variant="ghost" size="sm" asChild title="View job">
                                      <Link href={`/jobs/${rec.job_id}`}>
                                        <ExternalLink className="h-4 w-4" />
                                      </Link>
                                    </Button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
                    <span>
                      Showing {page * PAGE_SIZE + 1}–
                      {Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={page === 0}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        Previous
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={page >= totalPages - 1}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
    </Card>
  );
}
