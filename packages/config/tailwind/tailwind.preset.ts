import type { Config } from "tailwindcss";

/**
 * 口播IP智能体设计令牌（源自 docs/ui-mockup/assets/style.css，对齐 06 文档 §9.1 视觉基调）
 * 深空灰渐变 + 玻璃拟态 + 青紫品牌渐变
 */
export const tokens = {
  colors: {
    bg: {
      0: "#0B0E14",
      1: "#111827",
    },
    glass: {
      DEFAULT: "rgba(255,255,255,0.04)",
      strong: "rgba(255,255,255,0.07)",
    },
    stroke: {
      DEFAULT: "rgba(255,255,255,0.08)",
      strong: "rgba(255,255,255,0.14)",
    },
    text: {
      1: "#E5E7EB",
      2: "#9CA3AF",
      3: "#6B7280",
    },
    brand: {
      from: "#6366F1",
      to: "#22D3EE",
    },
    success: "#34D399",
    danger: "#F87171",
    warning: "#FBBF24",
    info: "#60A5FA",
  },
  borderRadius: {
    card: "14px",
  },
} as const;

const preset: Partial<Config> = {
  darkMode: "class",
  theme: {
    extend: {
      colors: tokens.colors,
      borderRadius: tokens.borderRadius,
      fontFamily: {
        sans: [
          "PingFang SC",
          "Microsoft YaHei",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
      },
      backgroundImage: {
        "brand-grad": "linear-gradient(135deg, #6366F1, #22D3EE)",
        "brand-grad-x": "linear-gradient(90deg, #6366F1, #22D3EE)",
        "app-bg":
          "radial-gradient(1200px 600px at 80% -10%, rgba(99,102,241,0.14), transparent 60%), radial-gradient(900px 500px at -10% 110%, rgba(34,211,238,0.10), transparent 55%), linear-gradient(160deg, #0B0E14, #111827)",
      },
      boxShadow: {
        cta: "0 6px 20px rgba(99,102,241,0.35)",
        "cta-hover": "0 10px 26px rgba(34,211,238,0.35)",
      },
    },
  },
};

export default preset;
