import clsx from "clsx";
import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}

export function Button({
  variant = "primary",
  className,
  children,
  ...rest
}: PropsWithChildren<BtnProps>) {
  return (
    <button
      {...rest}
      className={clsx(
        "inline-flex items-center justify-center px-3 py-1.5 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
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
