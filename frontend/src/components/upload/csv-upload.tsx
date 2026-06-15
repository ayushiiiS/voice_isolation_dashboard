"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { FileSpreadsheet, Loader2, Upload } from "lucide-react";

export function CsvUpload() {
  const { token } = useAuth();
  const router = useRouter();
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [fileName, setFileName] = useState<string | null>(null);

  const uploadFile = async (file: File) => {
    if (!token) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      toast.error("Please upload a CSV file");
      return;
    }

    setLoading(true);
    setFileName(file.name);
    setProgress(30);
    try {
      const res = await api.uploadCsv(token, file);
      setProgress(100);
      toast.success(res.message, {
        description: `${res.total_recordings} recordings queued — redirecting…`,
      });
      router.push(`/jobs/${res.job_id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
      setTimeout(() => {
        setProgress(0);
        setFileName(null);
      }, 1500);
    }
  };

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) uploadFile(file);
    },
    [token],
  );

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileSpreadsheet className="h-5 w-5 text-primary" />
          Batch CSV Upload
        </CardTitle>
        <CardDescription>
          CSV must include a <code className="text-primary">url</code> column with recording URLs.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 transition-colors ${
            dragging ? "border-primary bg-primary/5" : "border-border"
          }`}
        >
          <Upload className="mb-4 h-10 w-10 text-muted-foreground" />
          <p className="mb-2 text-sm font-medium">Drag & drop your CSV here</p>
          <p className="mb-4 text-xs text-muted-foreground">or click to browse</p>
          <input
            type="file"
            accept=".csv"
            className="hidden"
            id="csv-upload"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadFile(file);
            }}
          />
          <Button variant="outline" asChild disabled={loading}>
            <label htmlFor="csv-upload" className="cursor-pointer">
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Select CSV"}
            </label>
          </Button>
        </div>
        {fileName && (
          <p className="mt-3 text-sm text-muted-foreground">Uploading: {fileName}</p>
        )}
        {progress > 0 && <Progress value={progress} className="mt-3" />}
      </CardContent>
    </Card>
  );
}
