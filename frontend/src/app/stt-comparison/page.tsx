"use client";

import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { AuthGuard } from "@/components/layout/auth-guard";
import { SttComparisonView } from "@/components/stt/stt-comparison-view";
import { Button } from "@/components/ui/button";
import { useSearchParams } from "next/navigation";

export default function SttComparisonPage() {
  const searchParams = useSearchParams();
  const recordingId = searchParams.get("recordingId");

  return (
    <AuthGuard>
      <AppShell
        title="User Audio STT Comparison"
        subtitle="Compare STT provider confidence on isolated user speech only"
      >
        {recordingId ? (
          <SttComparisonView recordingId={recordingId} autoStart />
        ) : (
          <div className="rounded-lg border border-border/60 bg-muted/20 p-8 text-center">
            <p className="text-sm text-muted-foreground">
              Open a completed recording and use the <strong>STT Comparison</strong> tab,
              or pick a recording from the dashboard.
            </p>
            <Button asChild className="mt-4">
              <Link href="/dashboard">Go to Dashboard</Link>
            </Button>
          </div>
        )}
      </AppShell>
    </AuthGuard>
  );
}
