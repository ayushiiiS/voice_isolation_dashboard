"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import { AuthGuard } from "@/components/layout/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { InteractionViewer } from "@/components/interaction/interaction-viewer";
import { api, AnalyticsResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function InteractionPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || !id) return;
    api.analytics(token, id)
      .then(setData)
      .catch((err) => toast.error(err instanceof Error ? err.message : "Failed to load interaction"))
      .finally(() => setLoading(false));
  }, [token, id]);

  return (
    <AuthGuard>
      <AppShell title="Blue Machines Interaction Viewer">
        {loading || !data ? (
          <div className="flex h-64 items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          </div>
        ) : (
          <InteractionViewer data={data} />
        )}
      </AppShell>
    </AuthGuard>
  );
}
