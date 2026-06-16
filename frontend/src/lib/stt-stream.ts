"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  SttLanguageInfo,
  SttProviderState,
  SttSessionSnapshot,
  SttSelectionMode,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function wsBaseUrl(): string {
  const base = API_BASE.trim().replace(/\/+$/, "");
  if (base.startsWith("https://")) {
    return `wss://${base.slice("https://".length)}`;
  }
  if (base.startsWith("http://")) {
    return `ws://${base.slice("http://".length)}`;
  }
  return `ws://${base}`;
}

export interface UseSttStreamOptions {
  recordingId: string;
  language?: string | null;
  autoDetectLanguage?: boolean;
}

export interface SttStreamControls {
  snapshot: SttSessionSnapshot | null;
  connected: boolean;
  streaming: boolean;
  processing: boolean;
  detectingLanguage: boolean;
  detectedLanguage: SttLanguageInfo | null;
  providerNotice: string | null;
  error: string | null;
  startSession: () => Promise<void>;
  stopSession: () => void;
  setSelectionMode: (mode: SttSelectionMode, manualProvider?: string | null) => void;
  setHysteresis: (threshold: number) => void;
}

export function useSttStream(options: UseSttStreamOptions): SttStreamControls {
  const { token } = useAuth();
  const { recordingId, language = null, autoDetectLanguage = true } = options;

  const [snapshot, setSnapshot] = useState<SttSessionSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [detectingLanguage, setDetectingLanguage] = useState(false);
  const [detectedLanguage, setDetectedLanguage] = useState<SttLanguageInfo | null>(null);
  const [providerNotice, setProviderNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const sendWs = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const stopSession = useCallback(() => {
    sendWs({ type: "stop" });
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
    setProcessing(false);
    setDetectingLanguage(false);
  }, [sendWs]);

  const connectWebSocket = useCallback(
    (sessionId: string) => {
      if (!token) {
        throw new Error("Not authenticated");
      }

      const ws = new WebSocket(`${wsBaseUrl()}/stt/ws/${sessionId}`);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "auth", token }));
        setConnected(true);
        setError(null);
      };
      ws.onclose = (event) => {
        setConnected(false);
        setProcessing(false);
        setDetectingLanguage(false);
        if (event.code === 4401) {
          setError("Authentication failed — please log in again.");
        } else if (event.code === 4404) {
          setError("STT session expired — click Compare user audio STT again.");
        } else if (event.code !== 1000 && event.code !== 1005) {
          setError(`WebSocket closed (code ${event.code}). Click Compare again.`);
        }
      };
      ws.onerror = () => {
        setError("WebSocket connection failed — check backend is running on port 8000.");
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "snapshot") {
          setSnapshot(msg.data as SttSessionSnapshot);
        } else if (msg.type === "language_detecting") {
          setDetectingLanguage(true);
        } else if (msg.type === "language_detected") {
          setDetectingLanguage(false);
          setDetectedLanguage(msg.data as SttLanguageInfo);
        } else if (msg.type === "feed_started") {
          setProcessing(true);
        } else if (msg.type === "feed_complete") {
          setProcessing(false);
        } else if (msg.type === "providers_ready") {
          if (msg.ready < msg.total) {
            setProviderNotice(
              `${msg.ready}/${msg.total} STT providers connected without API keys — transcripts will be blank until keys are added.`,
            );
          }
        } else if (msg.type === "error") {
          setError(msg.message || "Stream error");
          setProviderNotice(null);
          setProcessing(false);
          setDetectingLanguage(false);
        }
      };
    },
    [token],
  );

  const startSession = useCallback(async () => {
    if (!token) {
      setError("Not authenticated");
      return;
    }
    if (!recordingId) {
      setError("A recording ID is required for user-audio STT comparison");
      return;
    }
    setError(null);
    setProviderNotice(null);
    setDetectedLanguage(null);

    const body: Record<string, unknown> = {
      recording_id: recordingId,
      auto_detect_language: autoDetectLanguage,
    };
    if (language) {
      body.language = language;
      body.auto_detect_language = false;
    }

    const res = await fetch(`${API_BASE}/stt/sessions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        localStorage.removeItem("token");
        throw new Error("Session expired — please log in again.");
      }
      throw new Error(data.detail || "Failed to create STT session");
    }
    const { session_id } = await res.json();
    connectWebSocket(session_id);
  }, [token, recordingId, language, autoDetectLanguage, connectWebSocket]);

  const setSelectionMode = useCallback(
    (mode: SttSelectionMode, manualProvider?: string | null) => {
      sendWs({
        type: "selection",
        selection_mode: mode,
        manual_provider: manualProvider ?? null,
      });
    },
    [sendWs],
  );

  const setHysteresis = useCallback(
    (threshold: number) => {
      sendWs({ type: "config", config: { hysteresis_threshold: threshold } });
    },
    [sendWs],
  );

  useEffect(() => () => stopSession(), [stopSession]);

  useEffect(() => {
    if (!connected || !detectingLanguage) return;
    const timer = setInterval(() => {
      sendWs({ type: "ping" });
    }, 20000);
    return () => clearInterval(timer);
  }, [connected, detectingLanguage, sendWs]);

  return {
    snapshot,
    connected,
    streaming: processing,
    processing,
    detectingLanguage,
    detectedLanguage,
    providerNotice,
    error,
    startSession,
    stopSession,
    setSelectionMode,
    setHysteresis,
  };
}

export function formatConfidence(value?: number | null): string {
  if (value == null) return "N/A";
  return `${Math.round(value)}%`;
}

export function statusVariant(
  status: SttProviderState["status"],
): "success" | "warning" | "destructive" | "secondary" {
  switch (status) {
    case "active":
      return "success";
    case "degraded":
    case "connecting":
      return "warning";
    case "error":
    case "disconnected":
      return "destructive";
    default:
      return "secondary";
  }
}

export function formatLanguageLabel(info?: SttLanguageInfo | null, fallback?: string): string {
  if (info?.language) {
    const pct =
      info.confidence != null && info.confidence > 0
        ? ` (${Math.round(info.confidence * 100)}%)`
        : "";
    return `${info.language}${pct}`;
  }
  return fallback ?? "Detecting…";
}
