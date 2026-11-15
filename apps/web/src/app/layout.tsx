import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "GigBid", description: "A freelancer copilot that finds, qualifies and drafts bids, and asks before it sends." };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        {children}
      </body>
    </html>
  );
}
