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

  analytics: (token: string, recordingId: string) =>
    request<AnalyticsResponse>(`/analytics/${recordingId}`, {}, token),

  reports: (token: string, recordingId: string) =>
    request<ReportLinks>(`/reports/${recordingId}`, {}, token),
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
