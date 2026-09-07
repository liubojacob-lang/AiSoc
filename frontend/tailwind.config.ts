/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0b0f1a",
          900: "#0f1526",
          850: "#131b30",
          800: "#182244",
          700: "#23304f",
          600: "#2c3c63",
        },
        accent: {
          DEFAULT: "#38bdf8",
          soft: "#38bdf822",
        },
        vio: "#8b5cf6",
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["Cascadia Code", "JetBrains Mono", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
