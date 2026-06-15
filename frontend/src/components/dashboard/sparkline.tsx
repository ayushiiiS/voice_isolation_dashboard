"use client";

import { cn } from "@/lib/utils";

interface SparklineProps {
  data: number[];
  className?: string;
  color?: string;
}

export function Sparkline({ data, className, color = "#818cf8" }: SparklineProps) {
  if (data.length < 2) {
    return (
      <svg viewBox="0 0 80 24" className={cn("h-6 w-20 opacity-40", className)}>
        <line x1="0" y1="12" x2="80" y2="12" stroke={color} strokeWidth="1.5" />
      </svg>
    );
  }

  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 80;
      const y = 22 - ((v - min) / range) * 18;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox="0 0 80 24" className={cn("h-6 w-20", className)} aria-hidden>
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
