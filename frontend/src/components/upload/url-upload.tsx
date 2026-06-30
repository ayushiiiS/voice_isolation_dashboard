"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Link2, Loader2 } from "lucide-react";

function normalizeRecordingUrl(raw: string): string {
  return raw.trim().replace(/^["']|["']$/g, "");
}

function validateRecordingUrl(raw: string): string | null {
  const value = normalizeRecordingUrl(raw);
  if (!value) return "Enter a recording URL";
  if (value.startsWith("file://")) {
    return "Local file paths cannot be used here — use Upload Audio File instead";
  }
  if (value.startsWith("[") || value.startsWith("{")) {
    return "Paste the recording URL only — not an error message or JSON";
  }
  if (/^https:\/\/console\.bluemachines\.ai\//i.test(value)) {
    if (!/[?&](conversationId|conversation_id|interactionId)=/i.test(value)) {
      return "Blue Machines link must include conversationId in the URL";
    }
    return null;
  }
  try {
    const parsed = new URL(value);
    if (["http:", "https:", "gs:"].includes(parsed.protocol)) {
      if (parsed.protocol !== "gs:" && !/\.(ogg|wav|mp3|m4a|flac|aac)(\?|$)/i.test(parsed.pathname)) {
        if (!parsed.hostname.includes("storage.googleapis.com")) {
          return "Use a direct audio URL (.ogg, .wav, …) or a Blue Machines console link";
        }
      }
      return null;
    }
  } catch {
    // URL() rejects gs:// on some engines; allow gs:// prefix explicitly
  }
  if (/^gs:\/\/.+\/.+/i.test(value)) {
    return null;
  }
  return "URL must start with https://, http://, gs://, or console.bluemachines.ai";
}

export function UrlUpload() {
  const { token } = useAuth();
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return;

    const validationError = validateRecordingUrl(url);
    if (validationError) {
      toast.error(validationError);
      return;
    }

    const normalizedUrl = normalizeRecordingUrl(url);
    setLoading(true);
    setProgress(20);
    try {
      const res = await api.uploadUrl(token, normalizedUrl);
      setProgress(100);
      toast.success(res.message, {
        description: "Redirecting to job status…",
      });
      setUrl("");
      router.push(`/jobs/${res.job_id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
      setTimeout(() => setProgress(0), 1000);
    }
  };

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Link2 className="h-5 w-5 text-primary" />
          Upload Recording URL
        </CardTitle>
        <CardDescription>
          Paste a direct audio URL, GCS path (<code className="text-xs">gs://</code>), or a
          Blue Machines console interaction link (with conversationId).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="url">Recording URL</Label>
            <Input
              id="url"
              placeholder="https://console.bluemachines.ai/... or gs://bucket/.../recording.ogg"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={loading}
            />
          </div>
          {progress > 0 && <Progress value={progress} />}
          <Button type="submit" disabled={loading || !url.trim()}>
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            Process Recording
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
