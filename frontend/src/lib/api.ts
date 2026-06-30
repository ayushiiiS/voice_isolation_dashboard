const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = "Request failed";
    try {
      const data = await res.json();
      if (Array.isArray(data.detail)) {
        detail = data.detail
          .map((item: { msg?: string; loc?: unknown[] }) => {
            const field = Array.isArray(item.loc)
              ? item.loc.filter((part) => part !== "body").join(".")
              : "";
            return field ? `${field}: ${item.msg ?? "invalid"}` : (item.msg ?? "invalid");
          })
          .join("; ");
      } else {
        detail = data.detail || data.message || detail;
      }
    } catch {
      detail = res.statusText;
    }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
  }

  return res.json();
}

export const api = {
  register: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  forgotPassword: (email: string) =>
    request<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  me: (token: string) =>
    request<User>("/auth/me", {}, token),

  dashboard: (token: string) =>
    request<DashboardStats>("/jobs/dashboard", {}, token),

  jobs: (token: string) =>
    request<{ jobs: Job[]; total: number }>("/jobs", {}, token),

  job: (token: string, id: string) =>
    request<JobDetail>(`/jobs/${id}`, {}, token),

  retryJob: (token: string, id: string) =>
    request<{ job_id: string; retried: number }>(`/jobs/${id}/retry`, { method: "POST" }, token),

  uploadUrl: (token: string, url: string) =>
    request<UploadResponse>("/upload/url", {
      method: "POST",
      body: JSON.stringify({ url }),
    }, token),

  uploadCsv: (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResponse>("/upload/csv", { method: "POST", body: form }, token);
  },

  uploadAudio: (token: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResponse>("/upload/file", { method: "POST", body: form }, token);
  },

  analytics: (token: string, recordingId: string) =>
    request<AnalyticsResponse>(`/analytics/${recordingId}`, {}, token),

  reports: (token: string, recordingId: string) =>
    request<ReportLinks>(`/reports/${recordingId}`, {}, token),

  sttProviders: (token: string) =>
    request<{ providers: SttProviderInfo[] }>("/stt/providers", {}, token),

  sttLanguages: (token: string) =>
    request<{ languages: SttLanguageOption[] }>("/stt/languages", {}, token),

  createSttSession: (
    token: string,
    config: {
      recording_id: string;
      auto_detect_language?: boolean;
      language?: string | null;
    },
  ) =>
    request<SttCreateSessionResponse>("/stt/sessions", {
      method: "POST",
      body: JSON.stringify(config),
    }, token),

  sttSession: (token: string, sessionId: string) =>
    request<SttSessionSnapshot>(`/stt/sessions/${sessionId}`, {}, token),

  updateSttSelection: (token: string, sessionId: string, body: SttUpdateSelectionRequest) =>
    request<SttSessionSnapshot>(`/stt/sessions/${sessionId}/selection`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }, token),
};

export interface User {
  id: string;
  email: string;
  created_at?: string;
  last_login?: string;
}

export interface Job {
  id: string;
  file_name?: string;
  source?: string;
  status: string;
  progress: number;
  total_recordings: number;
  completed_count: number;
  failed_count: number;
  duration_seconds?: number;
  created_at?: string;
  updated_at?: string;
}

export interface JobDetail extends Job {
  recordings: Recording[];
}

export interface Recording {
  id: string;
  file_name?: string;
  recording_url?: string;
  user_audio_url?: string;
  agent_audio_url?: string;
  original_audio_url?: string;
  status: string;
  duration_seconds?: number;
  error?: string;
  created_at?: string;
}

export interface DashboardStats {
  total_calls_processed: number;
  calls_today?: number;
  total_duration_seconds: number;
  avg_agent_latency_ms: number;
  avg_user_confidence: number;
  success_rate: number;
  failed_recordings?: number;
  queued_recordings?: number;
  processing_recordings?: number;
  queued_jobs?: number;
  processing_jobs?: number;
  recent_jobs: Job[];
  recent_recordings: DashboardRecording[];
}

export interface DashboardRecording {
  id: string;
  job_id?: string;
  file_name?: string;
  status: string;
  duration_seconds?: number;
  user_talk_time_seconds?: number;
  agent_talk_time_seconds?: number;
  avg_agent_latency_ms?: number;
  avg_user_confidence?: number;
  user_audio_url?: string;
  agent_audio_url?: string;
  storage_type?: "gcs" | "local";
  storage_uri?: string;
  upload_status?: "success" | "failed";
  gcs_error?: string;
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export interface UploadResponse {
  job_id: string;
  message: string;
  total_recordings: number;
}

export interface TranscriptEntry {
  speaker: string;
  role: string;
  text: string;
  start: number;
  end: number;
  confidence: number;
}

export interface TimelineSegment {
  speaker: string;
  role: string;
  start: number;
  end: number;
}

export interface LatencyPoint {
  user_utterance_end: number;
  agent_response_start: number;
  latency_ms: number;
}

export interface AnalyticsResponse {
  recording_id: string;
  job_id: string;
  call_duration_seconds: number;
  user_talk_time_seconds: number;
  agent_talk_time_seconds: number;
  avg_agent_latency_ms: number;
  latency_points: LatencyPoint[];
  avg_user_confidence: number;
  avg_agent_confidence: number;
  agent_interrupts_user: number;
  user_interrupts_agent: number;
  total_interruptions: number;
  silence_duration_seconds: number;
  speaker_switches: number;
  sentiment: string;
  sentiment_breakdown: { positive: number; neutral: number; negative: number };
  user_speaking_rate_wpm: number;
  agent_speaking_rate_wpm: number;
  transcript: TranscriptEntry[];
  timeline: TimelineSegment[];
  recording: Recording;
}

export interface ReportLinks {
  json_url?: string;
  csv_url?: string;
  pdf_url?: string;
}

export type SttSelectionMode = "auto" | "manual";

export interface SttProviderInfo {
  id: string;
  display_name: string;
  configured: boolean;
}

export interface SttSessionConfig {
  recording_id: string;
  auto_detect_language?: boolean;
  language?: string | null;
  enabled_providers?: string[];
  selection_mode?: SttSelectionMode;
  manual_provider?: string | null;
  hysteresis_threshold?: number;
  sample_rate?: number;
  language?: string;
}

export interface SttLanguageOption {
  code: string;
  label: string;
}

export interface SttLanguageInfo {
  language: string;
  language_code: string;
  confidence: number;
  method: string;
}

export interface SttCreateSessionResponse {
  session_id: string;
  ws_url: string;
}

export interface SttUpdateSelectionRequest {
  selection_mode: SttSelectionMode;
  manual_provider?: string | null;
  hysteresis_threshold?: number;
}

export interface SttProviderMetrics {
  provider: string;
  current_confidence?: number | null;
  average_confidence?: number | null;
  current_latency_ms: number;
  average_latency_ms: number;
  error_count: number;
  reconnect_count: number;
  uptime_seconds: number;
  transcript_count: number;
  last_error?: string | null;
}

export interface SttProviderState {
  provider: string;
  display_name: string;
  status: "connecting" | "active" | "degraded" | "disconnected" | "unavailable" | "error";
  partial_transcript: string;
  final_transcript: string;
  raw_confidence?: number | null;
  normalized_confidence?: number | null;
  composite_score?: number | null;
  latency_ms: number;
  ranking: number;
  metrics: SttProviderMetrics;
  error?: string | null;
  is_simulated: boolean;
}

export interface SttAudioQuality {
  score: number;
  sample_rate: number;
  channels: number;
  duration_seconds: number;
  clipping_ratio: number;
  silence_ratio: number;
  snr_db: number;
  warnings: string[];
  source_label?: string;
}

export interface SttLanguageCandidate {
  language: string;
  language_code: string;
  confidence: number;
}

export interface SttProviderScore {
  provider: string;
  confidence: number;
  completeness: number;
  language_match: number;
  composite: number;
  word_count: number;
}

export interface SttSessionSnapshot {
  session_id: string;
  selection_mode: SttSelectionMode;
  selected_provider?: string | null;
  auto_selected_provider?: string | null;
  best_provider?: string | null;
  best_confidence?: number | null;
  primary_transcript: string;
  consensus_transcript?: string;
  processed_transcript?: string;
  provider_raw_transcripts?: Record<string, string>;
  provider_scores?: SttProviderScore[];
  warnings?: string[];
  providers: SttProviderState[];
  source?: "microphone" | "isolated_user_audio";
  recording_id?: string | null;
  recording_file_name?: string | null;
  user_audio_url?: string | null;
  feed_progress?: number;
  feed_complete?: boolean;
  language?: string;
  detected_language?: string | null;
  language_code?: string | null;
  language_confidence?: number | null;
  language_detection_method?: string | null;
  language_mode?: "fixed" | "auto" | "multilingual";
  language_candidates?: SttLanguageCandidate[];
  language_hints?: string[];
  audio_quality?: SttAudioQuality | null;
  audio_source_type?: string | null;
  transcript_mode?: "consensus" | "single";
  updated_at: string;
}
