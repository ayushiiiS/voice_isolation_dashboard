"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AuthGuard } from "@/components/layout/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { ActionCenter } from "@/components/dashboard/action-center";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { RecordingsTable } from "@/components/dashboard/recordings-table";
import { RecentJobsTable } from "@/components/dashboard/recent-jobs-table";
import { SystemHealthBanner } from "@/components/dashboard/system-health-banner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, DashboardStats } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatDate } from "@/lib/utils";
import { toast } from "sonner";
import { Plus, RefreshCw, Search } from "lucide-react";

export default function DashboardContent() {
  const { token } = useAuth();
  const searchParams = useSearchParams();
  const defaultTab =
    (searchParams.get("tab") as "all" | "failed" | "processing" | "completed") || "all";

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [globalSearch, setGlobalSearch] = useState("");

  const load = useCallback(async (silent = false) => {
    if (!token) return;
    if (!silent) setRefreshing(true);
    try {
      const data = await api.dashboard(token);
      setStats(data);
      setLastUpdated(new Date());
    } catch (err) {
      if (!silent) {
        toast.error(err instanceof Error ? err.message : "Failed to load dashboard");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    load();
  }, [token, load]);

  useEffect(() => {
    if (!token || !stats) return;
    const hasActive =
      (stats.processing_recordings ?? 0) > 0 ||
      (stats.processing_jobs ?? 0) > 0 ||
      (stats.queued_recordings ?? 0) > 0 ||
      (stats.queued_jobs ?? 0) > 0;
    if (!hasActive) return;

    const interval = setInterval(() => load(true), 5000);
    return () => clearInterval(interval);
  }, [token, stats, load]);

  const filteredRecordings =
    stats?.recent_recordings.filter((r) => {
      if (!globalSearch.trim()) return true;
      const q = globalSearch.toLowerCase();
      return (
        (r.file_name || "").toLowerCase().includes(q) ||
        r.id.toLowerCase().includes(q)
      );
    }) ?? [];

  return (
    <AuthGuard>
      <AppShell
        title="Dashboard"
        subtitle="Voice Isolation & Call Analytics"
        lastUpdated={lastUpdated ? formatDate(lastUpdated.toISOString()) : undefined}
        actions={
          <>
            <div className="relative hidden md:block">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search recordings…"
                value={globalSearch}
                onChange={(e) => setGlobalSearch(e.target.value)}
                className="w-56 bg-muted/30 pl-9"
              />
            </div>
            <Button variant="outline" size="sm" onClick={() => load()} disabled={refreshing}>
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button size="sm" asChild>
              <Link href="/upload">
                <Plus className="h-4 w-4" />
                Upload Recording
              </Link>
            </Button>
          </>
        }
      >
        {loading || !stats ? (
          <div className="flex h-96 items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="h-10 w-10 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-sm text-muted-foreground">Loading dashboard…</p>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            <SystemHealthBanner stats={stats} />
            <ActionCenter stats={stats} onRefresh={() => load(true)} />
            <KpiCards stats={stats} />
            <RecordingsTable
              recordings={filteredRecordings}
              defaultTab={defaultTab}
              onRetryJob={() => load(true)}
            />
            <RecentJobsTable jobs={stats.recent_jobs} />
          </div>
        )}
      </AppShell>
    </AuthGuard>
  );
}
