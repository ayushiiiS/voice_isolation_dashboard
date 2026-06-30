"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { AuthGuard } from "@/components/layout/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { AnalyticsCharts } from "@/components/calls/analytics-charts";
import { AudioPlayerGroup } from "@/components/calls/audio-player";
import { TimelineView, TranscriptView } from "@/components/calls/transcript-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, AnalyticsResponse, ReportLinks } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatDuration } from "@/lib/utils";
import {
  ArrowLeft,
  BarChart3,
  Download,
  ExternalLink,
  FileText,
  Headphones,
  Radio,
  ScrollText,
} from "lucide-react";
import { SttComparisonView } from "@/components/stt/stt-comparison-view";

function MetricTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-border/40 bg-muted/20 p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

export default function CallDetailsPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [reports, setReports] = useState<ReportLinks | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || !id) return;
    const load = async () => {
      try {
        const [analytics, reportLinks] = await Promise.all([
          api.analytics(token, id),
          api.reports(token, id).catch(() => null),
        ]);
        setData(analytics);
        setReports(reportLinks);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Failed to load call details");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [token, id]);

  const silencePct =
    data && data.call_duration_seconds > 0
      ? ((data.silence_duration_seconds / data.call_duration_seconds) * 100).toFixed(1)
      : "0";

  return (
    <AuthGuard>
      <AppShell
        title={data?.recording.file_name || "Recording Details"}
        subtitle={data ? `Duration ${formatDuration(data.call_duration_seconds)}` : undefined}
        actions={
          data && (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href="/dashboard">
                  <ArrowLeft className="h-4 w-4" />
                  Dashboard
                </Link>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <Link href={`/interaction/${id}`}>
                  <ExternalLink className="h-4 w-4" />
                  Interaction
                </Link>
              </Button>
            </div>
          )
        }
      >
        {loading || !data ? (
          <div className="flex h-64 items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="success">{data.recording.status}</Badge>
              <span className="text-sm text-muted-foreground">
                Job …{data.job_id.slice(-8)}
              </span>
            </div>

            <Tabs defaultValue="overview" className="space-y-6">
              <TabsList className="h-auto flex-wrap justify-start bg-muted/40 p-1">
                <TabsTrigger value="overview" className="gap-1.5">
                  <BarChart3 className="h-4 w-4" /> Overview
                </TabsTrigger>
                <TabsTrigger value="audio" className="gap-1.5">
                  <Headphones className="h-4 w-4" /> Audio Separation
                </TabsTrigger>
                <TabsTrigger value="transcript" className="gap-1.5">
                  <ScrollText className="h-4 w-4" /> Transcript
                </TabsTrigger>
                <TabsTrigger value="analytics" className="gap-1.5">
                  <BarChart3 className="h-4 w-4" /> Analytics
                </TabsTrigger>
                <TabsTrigger value="stt" className="gap-1.5">
                  <Radio className="h-4 w-4" /> STT Comparison
                </TabsTrigger>
                <TabsTrigger value="logs" className="gap-1.5">
                  <FileText className="h-4 w-4" /> Reports
                </TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="space-y-6">
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <MetricTile
                    label="Agent Talk Time"
                    value={formatDuration(data.agent_talk_time_seconds)}
                  />
                  <MetricTile
                    label="User Talk Time"
                    value={formatDuration(data.user_talk_time_seconds)}
                  />
                  <MetricTile
                    label="Silence"
                    value={`${silencePct}%`}
                    sub={formatDuration(data.silence_duration_seconds)}
                  />
                  <MetricTile
                    label="Interruptions"
                    value={String(data.total_interruptions)}
                    sub={`Agent→User ${data.agent_interrupts_user} · User→Agent ${data.user_interrupts_agent}`}
                  />
                  <MetricTile
                    label="Avg Latency"
                    value={`${Math.round(data.avg_agent_latency_ms)} ms`}
                  />
                  <MetricTile
                    label="User STT Confidence"
                    value={`${(data.avg_user_confidence * 100).toFixed(1)}%`}
                  />
                  <MetricTile label="Sentiment" value={data.sentiment} />
                  <MetricTile
                    label="Speaker Switches"
                    value={String(data.speaker_switches)}
                  />
                </div>
                <AnalyticsCharts data={data} />
              </TabsContent>

              <TabsContent value="audio">
                <Card className="surface-elevated border-border/50">
                  <CardHeader>
                    <CardTitle>Separated Audio Tracks</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <AudioPlayerGroup
                      originalUrl={data.recording.original_audio_url}
                      userUrl={data.recording.user_audio_url}
                      agentUrl={data.recording.agent_audio_url}
                      fileBaseName={data.recording.file_name}
                    />
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="transcript">
                <div className="grid gap-6 lg:grid-cols-2">
                  <TranscriptView transcript={data.transcript} />
                  <TimelineView timeline={data.timeline} duration={data.call_duration_seconds} />
                </div>
              </TabsContent>

              <TabsContent value="analytics">
                <AnalyticsCharts data={data} />
              </TabsContent>

              <TabsContent value="stt">
                {data.recording.user_audio_url ? (
                  <SttComparisonView
                    recordingId={id}
                    recordingFileName={data.recording.file_name}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Isolated user audio is not available yet. Process this recording first.
                  </p>
                )}
              </TabsContent>

              <TabsContent value="logs">
                {reports ? (
                  <Card className="surface-elevated border-border/50">
                    <CardHeader>
                      <CardTitle>Export Reports</CardTitle>
                    </CardHeader>
                    <CardContent className="flex flex-wrap gap-3">
                      {reports.json_url && (
                        <Button variant="outline" asChild>
                          <a href={reports.json_url} target="_blank" rel="noopener noreferrer">
                            JSON Report
                          </a>
                        </Button>
                      )}
                      {reports.csv_url && (
                        <Button variant="outline" asChild>
                          <a href={reports.csv_url} target="_blank" rel="noopener noreferrer">
                            CSV Report
                          </a>
                        </Button>
                      )}
                      {reports.pdf_url && (
                        <Button asChild>
                          <a href={reports.pdf_url} target="_blank" rel="noopener noreferrer">
                            <Download className="h-4 w-4" />
                            PDF Report
                          </a>
                        </Button>
                      )}
                    </CardContent>
                  </Card>
                ) : (
                  <p className="text-sm text-muted-foreground">No reports available.</p>
                )}
              </TabsContent>
            </Tabs>
          </div>
        )}
      </AppShell>
    </AuthGuard>
  );
}
