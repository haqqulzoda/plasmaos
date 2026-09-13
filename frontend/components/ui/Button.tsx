"use client";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { clsx } from "clsx";
import Link from "next/link";
import type { ComponentProps } from "react";

export function ButtonLink({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ComponentProps<typeof Link> & {
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
}) {
  return (
    <Link
      {...props}
      prefetch={false}
      className={clsx(
        "ds-button",
        `ds-button-${variant}`,
        `ds-button-${size}`,
        className,
      )}
    />
  );
}
export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  ref?: React.Ref<HTMLButtonElement>;
  variant?: "primary" | "secondary" | "ghost" | "danger" | "icon";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
};
export function Button({
  variant = "primary",
  size = "md",
  loading,
  leadingIcon,
  trailingIcon,
  children,
  disabled,
  className,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "ds-button",
        `ds-button-${variant}`,
        `ds-button-${size}`,
        className,
      )}
    >
      {loading ? <Loader2 aria-hidden className="ds-spin" /> : leadingIcon}
      {children}
      {trailingIcon}
    </button>
  );
}
