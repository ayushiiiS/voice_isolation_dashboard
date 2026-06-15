"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await api.forgotPassword(email);
      setSent(true);
      toast.success(res.message);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md border-border/60 bg-card/80">
        <CardHeader>
          <CardTitle>Forgot password</CardTitle>
          <CardDescription>
            {sent
              ? "Check your email for reset instructions."
              : "Enter your email and we'll send reset instructions."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!sent && (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                Send reset link
              </Button>
            </form>
          )}
          <p className="mt-4 text-center text-sm">
            <Link href="/login" className="text-primary hover:underline">Back to login</Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
