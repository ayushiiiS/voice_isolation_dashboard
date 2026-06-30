"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Download, Loader2 } from "lucide-react";

interface AudioPlayerProps {
  originalUrl?: string;
  userUrl?: string;
  agentUrl?: string;
  fileBaseName?: string;
}

type Track = {
  key: string;
  label: string;
  url: string;
  fileName: string;
};

function buildDownloadName(base: string | undefined, suffix: string): string {
  if (!base) return suffix;
  const stem = base.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_");
  return `${stem}_${suffix}`;
}

async function downloadAudio(url: string, fileName: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

function TrackPlayer({ label, url }: { label: string; url: string }) {
  const [error, setError] = useState(false);

  if (error) {
    return (
      <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        Could not load {label.toLowerCase()} audio. Re-process the recording if this persists.
      </p>
    );
  }

  return (
    <audio
      controls
      preload="metadata"
      className="w-full"
      src={url}
      onError={() => setError(true)}
    >
      Your browser does not support audio playback.
    </audio>
  );
}

export function AudioPlayerGroup({
  originalUrl,
  userUrl,
  agentUrl,
  fileBaseName,
}: AudioPlayerProps) {
  const [downloading, setDownloading] = useState<string | null>(null);

  const tracks: Track[] = [
    {
      key: "original",
      label: "Original",
      url: originalUrl ?? "",
      fileName: buildDownloadName(fileBaseName, "original.wav"),
    },
    {
      key: "user",
      label: "User Only",
      url: userUrl ?? "",
      fileName: buildDownloadName(fileBaseName, "user_only.wav"),
    },
    {
      key: "agent",
      label: "Agent Only",
      url: agentUrl ?? "",
      fileName: buildDownloadName(fileBaseName, "agent_only.wav"),
    },
  ].filter((t): t is Track => Boolean(t.url));

  const handleDownload = async (track: Track) => {
    setDownloading(track.key);
    try {
      await downloadAudio(track.url, track.fileName);
      toast.success(`Downloaded ${track.label}`);
    } catch {
      toast.error(`Could not download ${track.label.toLowerCase()} audio`);
    } finally {
      setDownloading(null);
    }
  };

  const handleDownloadAll = async () => {
    setDownloading("all");
    try {
      for (const track of tracks) {
        await downloadAudio(track.url, track.fileName);
      }
      toast.success(`Downloaded ${tracks.length} audio files`);
    } catch {
      toast.error("Could not download all audio files");
    } finally {
      setDownloading(null);
    }
  };

  if (tracks.length === 0) {
    return (
      <Card className="border-border/60 bg-card/80">
        <CardHeader><CardTitle>Audio Player</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No audio tracks available yet.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle>Audio Player</CardTitle>
        {tracks.length > 1 && (
          <Button
            variant="outline"
            size="sm"
            disabled={downloading !== null}
            onClick={handleDownloadAll}
          >
            {downloading === "all" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            Download all
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <Tabs defaultValue={tracks[0]?.key}>
          <TabsList>
            {tracks.map((t) => (
              <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
          {tracks.map((t) => (
            <TabsContent key={t.key} value={t.key} className="space-y-3">
              <TrackPlayer label={t.label} url={t.url} />
              <Button
                variant="outline"
                size="sm"
                disabled={downloading !== null}
                onClick={() => handleDownload(t)}
              >
                {downloading === t.key ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                Download {t.label}
              </Button>
            </TabsContent>
          ))}
        </Tabs>

        <div className="rounded-lg border border-border/40 bg-muted/20 p-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Downloads
          </p>
          <div className="flex flex-wrap gap-2">
            {tracks.map((t) => (
              <Button
                key={`dl-${t.key}`}
                variant="secondary"
                size="sm"
                disabled={downloading !== null}
                onClick={() => handleDownload(t)}
              >
                {downloading === t.key ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                {t.label}
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
