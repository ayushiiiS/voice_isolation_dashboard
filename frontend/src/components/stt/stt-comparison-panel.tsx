"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  formatConfidence,
  statusVariant,
  type SttStreamControls,
} from "@/lib/stt-stream";
import type { SttProviderState, SttSelectionMode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Crown, Mic, Trophy } from "lucide-react";

const PROVIDER_OPTIONS = [
  { id: "auto", label: "Auto (highest confidence)" },
  { id: "deepgram", label: "Deepgram" },
  { id: "azure", label: "Azure Speech" },
  { id: "sarvam", label: "Sarvam AI" },
];

interface Props {
  stream: SttStreamControls;
  selectionMode: SttSelectionMode;
  manualProvider: string;
  onSelectionModeChange: (mode: SttSelectionMode) => void;
  onManualProviderChange: (provider: string) => void;
  hysteresis: number;
  onHysteresisChange: (value: number) => void;
}

export function SttComparisonPanel({
  stream,
  selectionMode,
  manualProvider,
  onSelectionModeChange,
  onManualProviderChange,
  hysteresis,
  onHysteresisChange,
}: Props) {
  const snapshot = stream.snapshot;
  const providers = snapshot?.providers ?? [];
  const sorted = [...providers].sort((a, b) => {
    const rankA = a.ranking || 999;
    const rankB = b.ranking || 999;
    return rankA - rankB;
  });

  const best = sorted.find((p) => p.ranking === 1);
  const selected = snapshot?.selected_provider;
  const autoSelected = snapshot?.auto_selected_provider;

  const activeSourceLabel =
    selectionMode === "auto"
      ? `Auto → ${autoSelected ?? "—"}`
      : `${PROVIDER_OPTIONS.find((o) => o.id === manualProvider)?.label ?? manualProvider} (Manual)`;

  return (
    <div className="space-y-6">
      <Card className="border-border/60 bg-card/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">User Audio STT Comparison</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Confidence scores reflect transcription of the isolated user track only.
            Default transcript mode uses weighted consensus across providers.
          </p>

          {(snapshot?.warnings?.length ?? 0) > 0 && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              {snapshot?.warnings?.map((warning) => (
                <p key={warning}>⚠ {warning}</p>
              ))}
            </div>
          )}

          <div className="grid gap-3 rounded-lg border border-border/40 bg-muted/20 p-4 md:grid-cols-3">
            <Metric label="Audio Quality Score" value={formatScore(snapshot?.audio_quality?.score)} />
            <Metric
              label="Language Confidence"
              value={formatPct(snapshot?.language_confidence)}
              warn={
                snapshot?.language_confidence != null &&
                snapshot.language_confidence <= 0.8
              }
            />
            <Metric
              label="Language Mode"
              value={snapshot?.language_mode ?? "fixed"}
              warn={snapshot?.language_mode === "multilingual"}
            />
          </div>
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Transcript source</span>
              <select
                className="rounded-md border border-border/60 bg-background px-3 py-2 text-sm"
                value={selectionMode === "auto" ? "auto" : manualProvider}
                onChange={(e) => {
                  const value = e.target.value;
                  if (value === "auto") {
                    onSelectionModeChange("auto");
                    stream.setSelectionMode("auto");
                  } else {
                    onSelectionModeChange("manual");
                    onManualProviderChange(value);
                    stream.setSelectionMode("manual", value);
                  }
                }}
              >
                {PROVIDER_OPTIONS.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Hysteresis threshold (%)</span>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={hysteresis}
                className="w-28 rounded-md border border-border/60 bg-background px-3 py-2 text-sm"
                onChange={(e) => {
                  const val = Number(e.target.value);
                  onHysteresisChange(val);
                  stream.setHysteresis(val);
                }}
              />
            </label>
          </div>

          <div className="grid gap-3 rounded-lg border border-border/40 bg-muted/20 p-4 md:grid-cols-2">
            <div className="flex items-center gap-2 text-sm">
              <Trophy className="h-4 w-4 text-amber-400" />
              <span>
                Best Provider:{" "}
                <strong>
                  {best?.display_name ?? "—"}{" "}
                  ({formatConfidence(best?.normalized_confidence)})
                </strong>
              </span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <Mic className="h-4 w-4 text-primary" />
              <span>
                Active Transcript Source: <strong>{activeSourceLabel}</strong>
              </span>
            </div>
          </div>

          {snapshot?.consensus_transcript && (
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
              <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                Consensus transcript (default)
              </p>
              <p className="text-sm leading-relaxed">{snapshot.consensus_transcript}</p>
            </div>
          )}

          {snapshot?.primary_transcript && (
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
              <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">
                Processed transcript
              </p>
              <p className="text-sm leading-relaxed">{snapshot.primary_transcript}</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">User STT Confidence Leaderboard</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border/40 text-left text-muted-foreground">
                <th className="pb-2 pr-4 font-medium">Provider</th>
                <th className="pb-2 pr-4 font-medium">Composite</th>
                <th className="pb-2 pr-4 font-medium">Confidence</th>
                <th className="pb-2 pr-4 font-medium">Latency</th>
                <th className="pb-2 pr-4 font-medium">Status</th>
                <th className="pb-2 font-medium">Transcript</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((provider) => (
                <ProviderRow
                  key={provider.provider}
                  provider={provider}
                  rawTranscript={snapshot?.provider_raw_transcripts?.[provider.provider]}
                  isBest={provider.provider === best?.provider}
                  isSelected={provider.provider === selected}
                  isAutoSelected={provider.provider === autoSelected}
                />
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function ProviderRow({
  provider,
  rawTranscript,
  isBest,
  isSelected,
  isAutoSelected,
}: {
  provider: SttProviderState;
  rawTranscript?: string;
  isBest: boolean;
  isSelected: boolean;
  isAutoSelected: boolean;
}) {
  const transcript = provider.final_transcript || provider.partial_transcript || "—";
  const isPartial = !provider.final_transcript && !!provider.partial_transcript;

  return (
    <tr
      className={cn(
        "border-b border-border/20 align-top",
        isSelected && "bg-primary/5",
        isBest && "ring-1 ring-inset ring-amber-500/20",
      )}
    >
      <td className="py-3 pr-4">
        <div className="flex items-center gap-2">
          {isBest && <Crown className="h-4 w-4 text-amber-400" />}
          <span className="font-medium">{provider.display_name}</span>
          {provider.is_simulated && (
            <Badge variant="outline" className="text-[10px]">
              Simulated
            </Badge>
          )}
          {isSelected && <Badge variant="default">Selected</Badge>}
          {isAutoSelected && selectionBadge()}
        </div>
        {provider.error && (
          <p className="mt-1 text-xs text-destructive">{provider.error}</p>
        )}
      </td>
      <td className="py-3 pr-4">
        <span className="font-semibold">
          {provider.composite_score != null
            ? `${Math.round(provider.composite_score * 100)}%`
            : "—"}
        </span>
      </td>
      <td className="py-3 pr-4">
        <span
          className={cn(
            "font-semibold",
            provider.normalized_confidence != null &&
              provider.normalized_confidence >= 90 &&
              "text-emerald-400",
            provider.normalized_confidence != null &&
              provider.normalized_confidence < 70 &&
              "text-amber-400",
          )}
        >
          {formatConfidence(provider.normalized_confidence)}
        </span>
        {provider.metrics.average_confidence != null && (
          <p className="text-xs text-muted-foreground">
            avg {formatConfidence(provider.metrics.average_confidence)}
          </p>
        )}
      </td>
      <td className="py-3 pr-4">
        <span>{Math.round(provider.latency_ms)} ms</span>
        {provider.metrics.average_latency_ms > 0 && (
          <p className="text-xs text-muted-foreground">
            avg {Math.round(provider.metrics.average_latency_ms)} ms
          </p>
        )}
      </td>
      <td className="py-3 pr-4">
        <Badge variant={statusVariant(provider.status)}>{provider.status}</Badge>
        {provider.metrics.error_count > 0 && (
          <p className="mt-1 text-xs text-muted-foreground">
            {provider.metrics.error_count} error(s)
          </p>
        )}
      </td>
      <td className="py-3">
        <p className={cn("max-w-md text-sm", isPartial && "italic text-muted-foreground")}>
          {transcript}
        </p>
        {rawTranscript && rawTranscript !== transcript && (
          <p className="mt-1 max-w-md text-xs text-muted-foreground">Raw: {rawTranscript}</p>
        )}
      </td>
    </tr>
  );
}

function Metric({
  label,
  value,
  warn = false,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="text-sm">
      <p className="text-muted-foreground">{label}</p>
      <p className={cn("font-semibold", warn && "text-amber-400")}>{value}</p>
    </div>
  );
}

function formatScore(score?: number) {
  if (score == null) return "—";
  return `${Math.round(score)}/100`;
}

function formatPct(value?: number | null) {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function selectionBadge() {
  return (
    <Badge variant="secondary" className="text-[10px]">
      Auto pick
    </Badge>
  );
}
