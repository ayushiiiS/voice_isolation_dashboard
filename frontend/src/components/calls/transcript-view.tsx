"use client";

import { AnalyticsResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function TranscriptView({ transcript }: { transcript: AnalyticsResponse["transcript"] }) {
  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader><CardTitle>Transcript</CardTitle></CardHeader>
      <CardContent className="max-h-96 space-y-3 overflow-y-auto">
        {transcript.map((entry, i) => (
          <div
            key={i}
            className={`rounded-lg p-3 ${
              entry.role === "user"
                ? "bg-indigo-500/10 border border-indigo-500/20"
                : "bg-cyan-500/10 border border-cyan-500/20"
            }`}
          >
            <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
              <span className="font-semibold uppercase">{entry.role}</span>
              <span>{entry.start.toFixed(1)}s – {entry.end.toFixed(1)}s</span>
            </div>
            <p className="text-sm">{entry.text}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function TimelineView({ timeline, duration }: { timeline: AnalyticsResponse["timeline"]; duration: number }) {
  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader><CardTitle>Speaker Timeline</CardTitle></CardHeader>
      <CardContent>
        <div className="relative h-16 w-full overflow-hidden rounded-lg bg-muted/30">
          {timeline.map((seg, i) => {
            const left = (seg.start / duration) * 100;
            const width = ((seg.end - seg.start) / duration) * 100;
            return (
              <div
                key={i}
                className={`absolute top-2 h-12 rounded ${
                  seg.role === "user" ? "bg-indigo-500/70" : "bg-cyan-500/70"
                }`}
                style={{ left: `${left}%`, width: `${Math.max(width, 0.2)}%` }}
                title={`${seg.role}: ${seg.start.toFixed(1)}s–${seg.end.toFixed(1)}s`}
              />
            );
          })}
        </div>
        <div className="mt-3 flex gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-indigo-500" /> User
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-cyan-500" /> Agent
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
