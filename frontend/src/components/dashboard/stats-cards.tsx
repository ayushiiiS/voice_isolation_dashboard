"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDuration } from "@/lib/utils";
import { DashboardStats } from "@/lib/api";
import {
  Activity,
  Clock,
  Gauge,
  Phone,
  TrendingUp,
} from "lucide-react";

const icons = [Phone, Clock, Gauge, TrendingUp, Activity];

export function StatsCards({ stats }: { stats: DashboardStats }) {
  const cards = [
    {
      title: "Total Calls Processed",
      value: stats.total_calls_processed.toLocaleString(),
      subtitle: "Completed recordings",
    },
    {
      title: "Total Duration",
      value: formatDuration(stats.total_duration_seconds),
      subtitle: `${Math.round(stats.total_duration_seconds / 60)} minutes total`,
    },
    {
      title: "Avg Agent Latency",
      value: `${Math.round(stats.avg_agent_latency_ms)} ms`,
      subtitle: "User end → agent start",
    },
    {
      title: "Avg User Confidence",
      value: `${(stats.avg_user_confidence * 100).toFixed(1)}%`,
      subtitle: "STT confidence score",
    },
    {
      title: "Success Rate",
      value: `${stats.success_rate.toFixed(1)}%`,
      subtitle: "Completed vs failed jobs",
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      {cards.map((card, i) => {
        const Icon = icons[i];
        return (
          <Card key={card.title} className="border-border/60 bg-card/80">
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {card.title}
              </CardTitle>
              <Icon className="h-4 w-4 text-primary" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{card.value}</div>
              <p className="text-xs text-muted-foreground">{card.subtitle}</p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
