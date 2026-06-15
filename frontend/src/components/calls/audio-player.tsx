"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface AudioPlayerProps {
  originalUrl?: string;
  userUrl?: string;
  agentUrl?: string;
}

export function AudioPlayerGroup({ originalUrl, userUrl, agentUrl }: AudioPlayerProps) {
  const tracks = [
    { key: "original", label: "Original", url: originalUrl },
    { key: "user", label: "User Only", url: userUrl },
    { key: "agent", label: "Agent Only", url: agentUrl },
  ].filter((t) => t.url);

  return (
    <Card className="border-border/60 bg-card/80">
      <CardHeader><CardTitle>Audio Player</CardTitle></CardHeader>
      <CardContent>
        <Tabs defaultValue={tracks[0]?.key}>
          <TabsList>
            {tracks.map((t) => (
              <TabsTrigger key={t.key} value={t.key}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
          {tracks.map((t) => (
            <TabsContent key={t.key} value={t.key}>
              <audio controls className="w-full" src={t.url}>
                Your browser does not support audio playback.
              </audio>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
    </Card>
  );
}
