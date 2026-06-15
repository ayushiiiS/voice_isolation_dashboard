"use client";

import { DashboardStats } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

type HealthState = "healthy" | "degraded" | "critical";

function computeHealth(stats: DashboardStats): {
  state: HealthState;
  label: string;
  description: string;
} {
  const failed = stats.failed_recordings ?? 0;
  const processing = (stats.processing_recordings ?? 0) + (stats.processing_jobs ?? 0);
  const successRate = stats.success_rate;

  if (failed > 0 && successRate < 50) {
    return {
      state: "critical",
      label: "Action Required",
      description: "Multiple failures detected — review failed recordings and retry.",
    };
  }
  if (failed > 0 || successRate < 90) {
    return {
      state: "degraded",
      label: "Degraded",
      description: "Some recordings failed or success rate is below target.",
    };
  }
  if (processing > 0) {
    return {
      state: "healthy",
      label: "Healthy",
      description: "System operating normally. Jobs are processing.",
    };
  }
  return {
    state: "healthy",
    label: "Healthy",
    description: "All systems operational. No active issues.",
  };
}

const stateStyles: Record<
  HealthState,
  { bg: string; border: string; dot: string; icon: typeof CheckCircle2 }
> = {
  healthy: {
    bg: "bg-emerald-500/8",
    border: "border-emerald-500/25",
    dot: "bg-emerald-400",
    icon: CheckCircle2,
  },
  degraded: {
    bg: "bg-amber-500/8",
    border: "border-amber-500/25",
    dot: "bg-amber-400",
    icon: AlertTriangle,
  },
  critical: {
    bg: "bg-red-500/8",
    border: "border-red-500/25",
    dot: "bg-red-400",
    icon: AlertTriangle,
  },
};

export function SystemHealthBanner({ stats }: { stats: DashboardStats }) {
  const health = computeHealth(stats);
  const styles = stateStyles[health.state];
  const Icon = styles.icon;

  const metrics = [
    {
      label: "Success Rate",
      value: `${stats.success_rate.toFixed(1)}%`,
      tone:
        stats.success_rate >= 90
          ? "text-emerald-400"
          : stats.success_rate >= 70
            ? "text-amber-400"
            : "text-red-400",
    },
    {
      label: "Failed",
      value: String(stats.failed_recordings ?? 0),
      tone: (stats.failed_recordings ?? 0) > 0 ? "text-red-400" : "text-muted-foreground",
    },
    {
      label: "Queued",
      value: String((stats.queued_recordings ?? 0) + (stats.queued_jobs ?? 0)),
      tone: "text-amber-400",
    },
    {
      label: "Processing",
      value: String((stats.processing_recordings ?? 0) + (stats.processing_jobs ?? 0)),
      tone: "text-indigo-400",
    },
  ];

  return (
    <div
      className={cn(
        "surface-elevated flex flex-col gap-4 rounded-xl p-5 md:flex-row md:items-center md:justify-between",
        styles.bg,
        styles.border,
      )}
    >
      <div className="flex items-start gap-4">
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
            styles.bg,
          )}
        >
          <Icon className={cn("h-5 w-5", styles.dot.replace("bg-", "text-"))} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Processing Health
            </span>
            <span className="flex items-center gap-1.5 text-sm font-semibold">
              <span className={cn("h-2 w-2 rounded-full", styles.dot)} />
              {health.label}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{health.description}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 md:gap-8">
        {metrics.map((m) => (
          <div key={m.label} className="text-center md:text-right">
            <p className="text-xs text-muted-foreground">{m.label}</p>
            <p className={cn("text-lg font-semibold tabular-nums", m.tone)}>{m.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
