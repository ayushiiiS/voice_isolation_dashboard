"use client";

import { Suspense } from "react";
import DashboardContent from "./dashboard-content";

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-96 items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      }
    >
      <DashboardContent />
    </Suspense>
  );
}
