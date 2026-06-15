"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthGuard } from "@/components/layout/auth-guard";
import { AppShell } from "@/components/layout/app-shell";
import { CsvUpload } from "@/components/upload/csv-upload";
import { UrlUpload } from "@/components/upload/url-upload";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ArrowLeft, Clock, FileSpreadsheet, Link2, Zap } from "lucide-react";

export default function UploadPage() {
  const router = useRouter();

  return (
    <AuthGuard>
      <AppShell
        title="Upload Recordings"
        subtitle="Process single URLs or batch CSV uploads"
        actions={
          <Button variant="outline" size="sm" onClick={() => router.push("/dashboard")}>
            <ArrowLeft className="h-4 w-4" />
            Dashboard
          </Button>
        }
      >
        <div className="mx-auto max-w-5xl space-y-8">
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              {
                icon: Link2,
                title: "Single URL",
                desc: "Paste one recording link",
              },
              {
                icon: FileSpreadsheet,
                title: "CSV Batch",
                desc: "Process hundreds at once",
              },
              {
                icon: Zap,
                title: "~2 min / call",
                desc: "Typical processing time",
              },
            ].map(({ icon: Icon, title, desc }) => (
              <Card key={title} className="surface-elevated border-border/50">
                <CardContent className="flex items-center gap-3 p-4">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <Icon className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <p className="font-medium">{title}</p>
                    <p className="text-xs text-muted-foreground">{desc}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card className="surface-elevated border-dashed border-primary/20 bg-primary/5">
            <CardContent className="flex flex-col items-center gap-2 py-8 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/15">
                <Clock className="h-7 w-7 text-primary" />
              </div>
              <p className="text-lg font-semibold">Upload & track in real time</p>
              <p className="max-w-md text-sm text-muted-foreground">
                After upload you&apos;ll be redirected to the job page. PyAnnote isolation
                separates agent and user audio, then analytics run automatically.
              </p>
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <UrlUpload />
            <CsvUpload />
          </div>
        </div>
      </AppShell>
    </AuthGuard>
  );
}
