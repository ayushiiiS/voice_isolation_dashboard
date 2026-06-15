"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  LogOut,
  Mic2,
  Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/upload", label: "Upload", icon: Upload },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col border-r border-border/60 bg-[#0a0f1a]">
      <div className="flex items-center gap-3 border-b border-border/60 px-5 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500/30 to-violet-500/20 text-primary ring-1 ring-indigo-500/20">
          <Mic2 className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-tight">Voice Isolation</p>
          <p className="text-[11px] text-muted-foreground">Call Analytics</p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 p-3">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all",
                active
                  ? "bg-primary/15 text-primary shadow-sm ring-1 ring-primary/20"
                  : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border/60 p-3">
        <div className="mb-3 rounded-lg bg-muted/30 px-3 py-2.5 ring-1 ring-border/40">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Signed in as</p>
          <p className="truncate text-sm font-medium">{user?.email}</p>
        </div>
        <Button
          variant="outline"
          className="w-full justify-start gap-2 border-border/60 bg-transparent hover:bg-muted/40"
          onClick={handleLogout}
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </Button>
      </div>
    </aside>
  );
}

export function AppShell({
  children,
  title,
  subtitle,
  lastUpdated,
  actions,
}: {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  lastUpdated?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-border/60 bg-background/90 px-6 py-5 backdrop-blur-md">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                {subtitle && <span>{subtitle}</span>}
                {lastUpdated && (
                  <>
                    {subtitle && <span className="hidden sm:inline">·</span>}
                    <span className="text-xs">Updated {lastUpdated}</span>
                  </>
                )}
              </div>
            </div>
            {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
          </div>
        </header>
        <div className="flex-1 p-6 md:p-8">{children}</div>
      </main>
    </div>
  );
}
