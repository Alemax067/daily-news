import clsx from "clsx";
import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...rest
}: PropsWithChildren<BtnProps>) {
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        size === "md" && "min-h-[40px] px-3.5 py-2 text-sm",
        size === "sm" && "px-3 py-1.5 text-sm",
        variant === "primary" && "bg-blue-600 text-white hover:bg-blue-700",
        variant === "secondary" && "bg-slate-200 text-slate-900 hover:bg-slate-300",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-700",
        variant === "ghost" && "text-slate-700 hover:bg-slate-100",
        className,
      )}
    >
      {children}
    </button>
  );
}
