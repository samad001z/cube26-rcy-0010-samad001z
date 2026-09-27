import { SearchX } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/notice";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <EmptyState
      icon={<SearchX aria-hidden />}
      title="Not found"
      action={
        <Button asChild>
          <Link href="/">Back to decisions</Link>
        </Button>
      }
    >
      There is no decision with that ID for your organisation.
    </EmptyState>
  );
}
