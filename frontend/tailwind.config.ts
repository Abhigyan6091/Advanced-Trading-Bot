import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "var(--page)",
        surface: "var(--surface)",
        sunken: "var(--sunken)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        muted: "var(--muted)",
        rule: "var(--rule)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        good: "var(--good)",
        warning: "var(--warning)",
        critical: "var(--critical)",
        "series-1": "var(--series-1)",
        "series-2": "var(--series-2)",
        "series-3": "var(--series-3)",
        "series-4": "var(--series-4)",
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
    },
  },
  plugins: [],
};

export default config;
