"use client"; // Error boundaries must be Client Components

import { RotateCw } from "lucide-react";

import { Notice } from "@/components/notice";
import { Button } from "@/components/ui/button";

export default function ErrorPage({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div className="max-w-xl space-y-4">
      <Notice tone="error" title="Something went wrong on this page">
        Nothing was changed. {error.digest && <span className="font-mono text-xs">Reference {error.digest}.</span>}
      </Notice>
      <Button onClick={() => retry()}>
        <RotateCw aria-hidden />
        Try again
      </Button>
    </div>
  );
}
