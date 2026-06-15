import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const IST_TIMEZONE = "Asia/Kolkata";

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${new Date(iso).toLocaleString("en-IN", {
    timeZone: IST_TIMEZONE,
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  })} IST`;
}

/** Turn API/exception strings into short, user-facing messages. */
export function formatError(raw: string | null | undefined): string {
  if (!raw) return "";
  if (raw.includes("_load_diarization")) {
    return "Internal processing error (diarization load). Retry the job.";
  }
  if (raw.includes("403 POST") && raw.includes("storage.googleapis.com/upload")) {
    return "Cloud upload denied — results saved locally. Check GCS write permissions.";
  }
  if (raw.includes("403 GET") || raw.includes("storage.objects.get")) {
    return "Cannot download source file — need read access to the source bucket.";
  }
  if (raw.includes("Could not decode") || raw.includes("ffmpeg failed")) {
    return "Audio decode failed — use a direct recording link or Blue Machines console URL.";
  }
  if (raw.includes("not a direct audio") || raw.includes("HTML or JSON")) {
    return "URL is not a direct audio file — paste a console.bluemachines.ai link or gs:// path.";
  }
  if (raw.includes("Could not download") && raw.includes("gs://")) {
    return "Cannot download from GCS — check read permission on the source bucket.";
  }
  if (raw.includes("expired") || raw.includes("InvalidAccessKeyId")) {
    return "Recording URL expired or invalid — use a fresh link or gs:// path.";
  }
  if (raw.includes("HF_TOKEN") || raw.includes("huggingface")) {
    return "Hugging Face token missing — set HF_TOKEN in .env for diarization.";
  }
  const firstLine = raw.split("\n")[0].trim();
  if (firstLine.length <= 120) return firstLine;
  return `${firstLine.slice(0, 117)}...`;
}
