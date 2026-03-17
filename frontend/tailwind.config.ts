import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        aria: {
          dark: "var(--aria-dark)",
          surface: "var(--aria-surface)",
          border: "var(--aria-border)",
          accent: "var(--aria-accent)",
          text: "var(--aria-text)",
          muted: "var(--aria-muted)",
        },
      },
    },
  },
  plugins: [],
};

export default config;
