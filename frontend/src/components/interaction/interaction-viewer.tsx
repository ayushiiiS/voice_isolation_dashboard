"use client";

import { AnalyticsResponse } from "@/lib/api";
import { formatDuration } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AnalyticsCharts } from "@/components/calls/analytics-charts";
import { AudioPlayerGroup } from "@/components/calls/audio-player";
import { TimelineView, TranscriptView } from "@/components/calls/transcript-view";

export function InteractionViewer({ data }: { data: AnalyticsResponse }) {
  const rec = data.recording;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        {[
          { label: "Duration", value: formatDuration(data.call_duration_seconds) },
          { label: "Avg Latency", value: `${Math.round(data.avg_agent_latency_ms)} ms` },
          { label: "User Confidence", value: `${(data.avg_user_confidence * 100).toFixed(0)}%` },
          { label: "Sentiment", value: data.sentiment },
        ].map((m) => (
          <Card key={m.label} className="border-border/60 bg-card/80">
            <CardContent className="pt-6">
              <p className="text-xs text-muted-foreground">{m.label}</p>
              <p className="text-xl font-semibold capitalize">{m.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-6">
          <Card className="border-border/60 bg-card/80">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>Waveform & Timeline</CardTitle>
                <Badge variant="secondary">{rec.file_name || rec.id.slice(-8)}</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <TimelineView timeline={data.timeline} duration={data.call_duration_seconds} />
              <div className="rounded-lg bg-muted/20 p-4">
                <div className="flex h-24 items-end gap-0.5">
                  {data.timeline.slice(0, 80).map((seg, i) => (
                    <div
                      key={i}
                      className={`flex-1 rounded-t ${
                        seg.role === "user" ? "bg-indigo-500/60" : "bg-cyan-500/60"
                      }`}
                      style={{
                        height: `${20 + ((seg.end - seg.start) / data.call_duration_seconds) * 200}%`,
                      }}
                    />
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <AnalyticsCharts data={data} />
        </div>

        <div className="space-y-6">
          <AudioPlayerGroup
            originalUrl={rec.original_audio_url}
            userUrl={rec.user_audio_url}
            agentUrl={rec.agent_audio_url}
            fileBaseName={rec.file_name}
          />
          <TranscriptView transcript={data.transcript} />

          <Card className="border-border/60 bg-card/80">
            <CardHeader><CardTitle>Interaction Metrics</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between"><span>Speaker switches</span><span>{data.speaker_switches}</span></div>
              <div className="flex justify-between"><span>Interruptions</span><span>{data.total_interruptions}</span></div>
              <div className="flex justify-between"><span>User WPM</span><span>{data.user_speaking_rate_wpm}</span></div>
              <div className="flex justify-between"><span>Agent WPM</span><span>{data.agent_speaking_rate_wpm}</span></div>
              <div className="flex justify-between"><span>Agent interrupts user</span><span>{data.agent_interrupts_user}</span></div>
              <div className="flex justify-between"><span>User interrupts agent</span><span>{data.user_interrupts_agent}</span></div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
