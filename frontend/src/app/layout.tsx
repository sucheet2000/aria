import type { Metadata } from "next";
import { Manrope, DM_Sans, Space_Grotesk } from "next/font/google";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  weight: ["300", "400", "600"],
  variable: "--font-display",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-body",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-data",
});

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
    <html
      lang="en"
      className={`${manrope.variable} ${dmSans.variable} ${spaceGrotesk.variable}`}
    >
      <head>
        <meta name="theme-color" content="#0e0e12" />
      </head>
      <body style={{ minHeight: "100vh" }}>{children}</body>
    </html>
  );
}
