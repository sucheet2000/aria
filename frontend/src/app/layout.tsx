import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARIA — Multimodal AGI Avatar",
  description: "ARIA: Adaptive Real-time Intelligence Avatar",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-aria-dark text-slate-100">{children}</body>
    </html>
  );
}
