import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#142033",
        canvas: "#edf2f5",
        asbestos: "#dc2626",
        cleaned: "#0f8b8d",
        ambiguous: "#7c3aed"
      }
    }
  },
  plugins: []
};

export default config;
