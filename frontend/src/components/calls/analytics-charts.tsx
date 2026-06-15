"use client";

import { AnalyticsResponse } from "@/lib/api";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function AnalyticsCharts({ data }: { data: AnalyticsResponse }) {
  const talkTimeData = [
    { name: "User", seconds: data.user_talk_time_seconds, fill: "#6366f1" },
    { name: "Agent", seconds: data.agent_talk_time_seconds, fill: "#22d3ee" },
    { name: "Silence", seconds: data.silence_duration_seconds, fill: "#64748b" },
  ];

  const latencyData = data.latency_points.slice(0, 20).map((p, i) => ({
    turn: i + 1,
    latency: p.latency_ms,
  }));

  const confidenceData = data.transcript.slice(0, 30).map((t, i) => ({
    idx: i + 1,
    confidence: t.confidence * 100,
    role: t.role,
  }));

  const sentimentData = [
    { name: "Positive", value: data.sentiment_breakdown.positive * 100, fill: "#22c55e" },
    { name: "Neutral", value: data.sentiment_breakdown.neutral * 100, fill: "#94a3b8" },
    { name: "Negative", value: data.sentiment_breakdown.negative * 100, fill: "#ef4444" },
  ];

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card className="border-border/60 bg-card/80">
        <CardHeader><CardTitle>Talk Time</CardTitle></CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={talkTimeData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Bar dataKey="seconds" radius={[6, 6, 0, 0]}>
                {talkTimeData.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card/80">
        <CardHeader><CardTitle>Agent Response Latency</CardTitle></CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={latencyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="turn" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" unit=" ms" />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Line type="monotone" dataKey="latency" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card/80">
        <CardHeader><CardTitle>STT Confidence</CardTitle></CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={confidenceData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="idx" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" domain={[0, 100]} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Line type="monotone" dataKey="confidence" stroke="#22d3ee" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card/80">
        <CardHeader><CardTitle>Sentiment</CardTitle></CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={sentimentData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                {sentimentData.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
            </PieChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}
