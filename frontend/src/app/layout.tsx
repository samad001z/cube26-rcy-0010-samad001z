import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";

import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

const DESCRIPTION =
  "Recovery Manager review console: decisions on fee and reimbursement charges, with the evidence and reasons behind them.";

export const metadata: Metadata = {
  metadataBase: new URL("https://alibi-recovery.vercel.app"),
  title: { default: "Alibi", template: "%s · Alibi" },
  description: DESCRIPTION,
  openGraph: {
    title: "Alibi: every charge deserves an alibi",
    description: DESCRIPTION,
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
      </body>
    </html>
  );
}
