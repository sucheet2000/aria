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
          dark: "#0a0a0f",
          surface: "#111118",
          accent: "#6366f1",
          glow: "#818cf8",
        },
      },
    },
  },
  plugins: [],
};

export default config;
