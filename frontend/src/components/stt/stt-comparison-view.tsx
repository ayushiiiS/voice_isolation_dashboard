"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { SttComparisonPanel } from "@/components/stt/stt-comparison-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import type { SttSelectionMode } from "@/lib/api";
import { formatLanguageLabel, useSttStream } from "@/lib/stt-stream";
import { useAuth } from "@/lib/auth-context";
import { Play, Square } from "lucide-react";

interface Props {
  recordingId: string;
  recordingFileName?: string;
  autoStart?: boolean;
}

export function SttComparisonView({ recordingId, recordingFileName, autoStart = false }: Props) {
  const { token } = useAuth();
  const [languages, setLanguages] = useState<{ code: string; label: string }[]>([]);
  const [languageOverride, setLanguageOverride] = useState("");
  const [selectionMode, setSelectionMode] = useState<SttSelectionMode>("auto");
  const [manualProvider, setManualProvider] = useState("deepgram");
  const [hysteresis, setHysteresis] = useState(5);

  const stream = useSttStream({
    recordingId,
    language: languageOverride || null,
    autoDetectLanguage: !languageOverride,
  });

  useEffect(() => {
    if (!token) return;
    api.sttLanguages(token).then((res) => setLanguages(res.languages)).catch(() => {});
  }, [token]);

  const handleStart = async () => {
    try {
      await stream.startSession();
      toast.success("Detecting language and running user-audio STT comparison");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start session");
    }
  };

  useEffect(() => {
    if (autoStart && !stream.connected && !stream.error) {
      handleStart();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart, recordingId]);

  const progressPct = Math.round((stream.snapshot?.feed_progress ?? 0) * 100);
  const feedComplete = stream.snapshot?.feed_complete;
  const snapshot = stream.snapshot;
  const activeLanguage =
    stream.detectedLanguage?.language ??
    stream.snapshot?.detected_language ??
    stream.snapshot?.language;

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Language is detected from the isolated user audio, then each STT provider transcribes
        in that language. Agent audio is never used.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Language</span>
          <select
            className="min-w-[220px] rounded-md border border-border/60 bg-background px-3 py-2 text-sm"
            value={languageOverride}
            disabled={stream.connected}
            onChange={(e) => setLanguageOverride(e.target.value)}
          >
            <option value="">Auto-detect from user audio</option>
            {languages.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={stream.connected ? "success" : "secondary"}>
          {stream.connected ? "Connected" : "Disconnected"}
        </Badge>
        <Badge variant="outline">
          User audio only
          {recordingFileName ? `: ${recordingFileName}` : ""}
        </Badge>
        {stream.detectingLanguage && <Badge variant="warning">Detecting language…</Badge>}
        {snapshot?.audio_quality && (
          <Badge variant={snapshot.audio_quality.score >= 60 ? "secondary" : "warning"}>
            Audio quality: {Math.round(snapshot.audio_quality.score)}/100
          </Badge>
        )}
        {activeLanguage && !stream.detectingLanguage && (
          <Badge variant="secondary">
            STT language: {formatLanguageLabel(stream.detectedLanguage, activeLanguage)}
          </Badge>
        )}
        {!stream.connected ? (
          <Button onClick={handleStart} className="gap-2" size="sm">
            <Play className="h-4 w-4" />
            Compare user audio STT
          </Button>
        ) : (
          <>
            {stream.processing && !feedComplete && (
              <Badge variant="warning">Transcribing user audio…</Badge>
            )}
            {feedComplete && <Badge variant="success">User STT complete</Badge>}
            <Button variant="destructive" onClick={() => stream.stopSession()} className="gap-2" size="sm">
              <Square className="h-4 w-4" />
              End session
            </Button>
          </>
        )}
      </div>

      {stream.connected && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>User audio progress</span>
            <span>{progressPct}%</span>
          </div>
          <Progress value={progressPct} className="h-2" />
        </div>
      )}

      {stream.providerNotice && (
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm text-blue-200">
          {stream.providerNotice}
        </div>
      )}

      {stream.error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {stream.error}
        </div>
      )}

      <SttComparisonPanel
        stream={stream}
        selectionMode={selectionMode}
        manualProvider={manualProvider}
        onSelectionModeChange={setSelectionMode}
        onManualProviderChange={setManualProvider}
        hysteresis={hysteresis}
        onHysteresisChange={setHysteresis}
      />
    </div>
  );
}
