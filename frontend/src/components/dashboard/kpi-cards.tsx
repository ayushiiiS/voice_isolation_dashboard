"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { DashboardStats } from "@/lib/api";
import { formatDuration } from "@/lib/utils";
import { cn } from "@/lib/utils";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Clock,
  Gauge,
  Minus,
  Phone,
  TrendingUp,
} from "lucide-react";
import { Sparkline } from "./sparkline";

function TrendBadge({ value, suffix = "" }: { value: number | null; suffix?: string }) {
  if (value === null) {
    return (
      <span className="flex items-center gap-0.5 text-xs text-muted-foreground">
        <Minus className="h-3 w-3" /> —
      </span>
    );
  }
  const up = value >= 0;
  return (
    <span
      className={cn(
        "flex items-center gap-0.5 text-xs font-medium",
        up ? "text-emerald-400" : "text-red-400",
      )}
    >
      {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
      {Math.abs(value).toFixed(0)}
      {suffix}
    </span>
  );
}

function latencyStatus(ms: number): { label: string; variant: "success" | "warning" | "destructive" } {
  if (ms <= 800) return { label: "Good", variant: "success" };
  if (ms <= 1500) return { label: "Warning", variant: "warning" };
  return { label: "Critical", variant: "destructive" };
}

function successVariant(rate: number): "success" | "warning" | "destructive" {
  if (rate >= 90) return "success";
  if (rate >= 70) return "warning";
  return "destructive";
}

const variantColors = {
  success: "#34d399",
  warning: "#fbbf24",
  destructive: "#f87171",
};

export function KpiCards({ stats }: { stats: DashboardStats }) {
  const avgDuration =
    stats.total_calls_processed > 0
      ? stats.total_duration_seconds / stats.total_calls_processed
      : 0;
  const latency = latencyStatus(stats.avg_agent_latency_ms);
  const successVar = successVariant(stats.success_rate);
  const confidencePct = stats.avg_user_confidence * 100;

  const sparkFromRecordings = (field: "completed" | "failed") => {
    const counts = stats.recent_recordings
      .slice(0, 7)
      .reverse()
      .map((r) => (field === "completed" ? (r.status === "completed" ? 1 : 0) : r.status === "failed" ? 1 : 0));
    return counts.length >= 2 ? counts : [0, 0, 0, 1, 0, 1, stats.calls_today ?? 0];
  };

  const cards = [
    {
      title: "Total Calls Processed",
      value: stats.total_calls_processed.toLocaleString(),
      sub: `${stats.calls_today ?? 0} today`,
      trend: stats.calls_today ? stats.calls_today : null,
      trendSuffix: " today",
      icon: Phone,
      spark: sparkFromRecordings("completed"),
      sparkColor: "#818cf8",
      tooltip: "Completed voice isolation jobs",
    },
    {
      title: "Avg Processing Time",
      value: formatDuration(avgDuration),
      sub: `${formatDuration(stats.total_duration_seconds)} total`,
      trend: null,
      icon: Clock,
      spark: [avgDuration, avgDuration * 0.9, avgDuration * 1.1, avgDuration],
      sparkColor: "#60a5fa",
      tooltip: "Average call duration processed",
    },
    {
      title: "Agent Response Latency",
      value: `${Math.round(stats.avg_agent_latency_ms)} ms`,
      sub: latency.label,
      trend: null,
      icon: Gauge,
      spark: [stats.avg_agent_latency_ms, stats.avg_agent_latency_ms * 0.95, stats.avg_agent_latency_ms],
      sparkColor: variantColors[latency.variant],
      tooltip: "User end → agent start",
      badge: latency,
    },
    {
      title: "Voice Detection Confidence",
      value: `${confidencePct.toFixed(1)}%`,
      sub: "STT confidence",
      trend: null,
      icon: TrendingUp,
      spark: [confidencePct * 0.9, confidencePct, confidencePct * 0.95, confidencePct],
      sparkColor: "#a78bfa",
      tooltip: "Average speech-to-text confidence",
      progress: confidencePct,
    },
    {
      title: "Success Rate",
      value: `${stats.success_rate.toFixed(1)}%`,
      sub: "Completed vs failed",
      trend: stats.success_rate >= 90 ? stats.success_rate : - (100 - stats.success_rate),
      trendSuffix: "%",
      icon: Activity,
      spark: [stats.success_rate, stats.success_rate, stats.success_rate],
      sparkColor: variantColors[successVar],
      tooltip: "Share of recordings that completed successfully",
      large: true,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <Card
            key={card.title}
            className="surface-elevated border-border/50 transition-colors hover:border-border"
            title={card.tooltip}
          >
            <CardContent className="p-5">
              <div className="flex items-start justify-between gap-2">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                  <Icon className="h-4 w-4 text-primary" />
                </div>
                <Sparkline data={card.spark} color={card.sparkColor} />
              </div>
              <p className="mt-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {card.title}
              </p>
              <p
                className={cn(
                  "mt-1 font-bold tabular-nums tracking-tight",
                  card.large ? "text-3xl" : "text-2xl",
                  card.title === "Success Rate" &&
                    (successVar === "success"
                      ? "text-emerald-400"
                      : successVar === "warning"
                        ? "text-amber-400"
                        : "text-red-400"),
                )}
              >
                {card.value}
              </p>
              <div className="mt-2 flex items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">{card.sub}</p>
                {"trend" in card && card.trend !== undefined && (
                  <TrendBadge value={card.trend} suffix={card.trendSuffix} />
                )}
              </div>
              {"progress" in card && card.progress !== undefined && (
                <Progress value={card.progress} className="mt-3 h-1.5" />
              )}
              {"badge" in card && card.badge && (
                <span
                  className={cn(
                    "mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                    card.badge.variant === "success" && "bg-emerald-500/15 text-emerald-400",
                    card.badge.variant === "warning" && "bg-amber-500/15 text-amber-400",
                    card.badge.variant === "destructive" && "bg-red-500/15 text-red-400",
                  )}
                >
                  {card.badge.label}
                </span>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
