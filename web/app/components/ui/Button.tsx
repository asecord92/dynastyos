import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md" | "lg";

const base =
  "inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition disabled:opacity-40 disabled:cursor-not-allowed";

const variants: Record<Variant, string> = {
  primary: "bg-violet-600 text-white hover:bg-violet-700 active:translate-y-px",
  secondary: "bg-gray-50 text-gray-700 border border-gray-200 hover:border-gray-300",
  ghost: "text-gray-500 hover:text-gray-800 hover:bg-gray-100",
};

const sizes: Record<Size, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-sm",
};

/**
 * Shared button: muted-indigo primary, outline secondary, ghost for icons/links.
 * Replaces the scattered `bg-black` / outline button strings. Focus rings come
 * from the global :focus-visible style.
 */
export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; children?: ReactNode }) {
  return (
    <button className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} {...props}>
      {children}
    </button>
  );
}
