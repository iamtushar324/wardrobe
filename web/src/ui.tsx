import clsx from "clsx";
import { Check, ChevronDown, Loader2, X } from "lucide-react";
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export const cx = clsx;

// ---------------- buttons & inputs ----------------
type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "soft";
  size?: "sm" | "md" | "lg" | "icon";
  loading?: boolean;
};

export function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-full font-medium transition-colors select-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 disabled:pointer-events-none",
        size === "sm" && "h-8 px-3 text-[13px]",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-6 text-[15px]",
        size === "icon" && "h-9 w-9",
        variant === "primary" && "bg-ink text-paper hover:bg-black",
        variant === "secondary" && "bg-white border border-line text-ink hover:bg-canvas",
        variant === "ghost" && "text-ink-2 hover:bg-canvas",
        variant === "soft" && "bg-accent-soft text-accent hover:bg-[#d6e6de]",
        variant === "danger" && "bg-white border border-[#f1c9c4] text-danger hover:bg-[#fdf1ef]",
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : null}
      {children}
    </button>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "h-10 w-full rounded-xl border border-line bg-white px-3 text-sm outline-none transition placeholder:text-muted",
        "focus:border-ink-2 focus:ring-4 focus:ring-[#ebe7e0]",
        props.className,
      )}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        "w-full rounded-xl border border-line bg-white px-3 py-2 text-sm outline-none transition placeholder:text-muted",
        "focus:border-ink-2 focus:ring-4 focus:ring-[#ebe7e0]",
        props.className,
      )}
    />
  );
}

export function Select({ options, value, onChange, className, placeholder }: {
  options: (string | { value: string; label: string; disabled?: boolean })[];
  value: string;
  onChange: (v: string) => void;
  className?: string;
  placeholder?: string;
}) {
  return (
    <div className={cx("relative", className)}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full appearance-none rounded-xl border border-line bg-white pl-3 pr-9 text-sm outline-none focus:border-ink-2 focus:ring-4 focus:ring-[#ebe7e0]"
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => {
          const v = typeof o === "string" ? o : o.value;
          const l = typeof o === "string" ? cap(o) : o.label;
          return (
            <option key={v} value={v} disabled={typeof o !== "string" && o.disabled}>
              {l}
            </option>
          );
        })}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-3 size-4 text-muted" />
    </div>
  );
}

export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cx("block", className)}>
      <span className="mb-1.5 flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide text-muted">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </div>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2.5 text-left text-sm disabled:opacity-50"
    >
      <span className={cx("relative block h-6 w-10 shrink-0 rounded-full transition-colors", checked ? "bg-accent" : "bg-[#d9d4cb]")}>
        <span className={cx("absolute left-0 top-0.5 size-5 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
      </span>
      {label}
    </button>
  );
}

export function Chip({ active, onClick, children, count, className, onRemove }: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  count?: number;
  className?: string;
  onRemove?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors whitespace-nowrap",
        active ? "border-ink bg-ink text-paper" : "border-line bg-white text-ink-2 hover:border-[#cfc9bf]",
        className,
      )}
    >
      {children}
      {count !== undefined && <span className={cx("text-[11px] tabular-nums", active ? "text-[#cfc9bf]" : "text-muted")}>{count}</span>}
      {onRemove && (
        <span
          role="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="-mr-1 rounded-full p-0.5 hover:bg-white/20"
        >
          <X className="size-3.5" />
        </span>
      )}
    </button>
  );
}

export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "accent" | "warn" | "danger" | "dark"; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        tone === "neutral" && "bg-canvas text-ink-2",
        tone === "accent" && "bg-accent-soft text-accent",
        tone === "warn" && "bg-[#fdf3e2] text-warn",
        tone === "danger" && "bg-[#fdecea] text-danger",
        tone === "dark" && "bg-ink/80 text-paper backdrop-blur",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Swatch({ hex, size = 14, ring }: { hex: string; size?: number; ring?: boolean }) {
  return (
    <span
      className={cx("inline-block shrink-0 rounded-full border border-black/10", ring && "ring-2 ring-ink ring-offset-2")}
      style={{ width: size, height: size, background: hex }}
    />
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-5 animate-spin text-muted", className)} />;
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-2xl border border-line bg-white", className)}>{children}</div>;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-6 py-20 text-center">
      {icon && <div className="mb-4 grid size-14 place-items-center rounded-2xl bg-canvas text-ink-2">{icon}</div>}
      <h3 className="font-display text-xl">{title}</h3>
      {children && <p className="mt-2 text-sm leading-relaxed text-muted">{children}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function Progress({ value, tone = "ink", className }: { value: number; tone?: "ink" | "accent" | "warn" | "danger"; className?: string }) {
  const v = Math.max(0, Math.min(100, value || 0));
  return (
    <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-canvas", className)}>
      <div
        className={cx("h-full rounded-full transition-all", tone === "ink" && "bg-ink", tone === "accent" && "bg-accent", tone === "warn" && "bg-warn", tone === "danger" && "bg-danger")}
        style={{ width: `${v}%` }}
      />
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, className }: {
  value: T;
  options: { value: T; label: ReactNode; icon?: ReactNode }[];
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={cx("inline-flex rounded-full border border-line bg-white p-1", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cx(
            "inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors",
            value === o.value ? "bg-ink text-paper" : "text-ink-2 hover:text-ink",
          )}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---------------- overlays ----------------
export function Modal({ open, onClose, title, children, wide, footer }: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  wide?: boolean;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={onClose} />
      <div
        className={cx(
          "fade-in relative flex max-h-[92vh] w-full flex-col rounded-t-3xl bg-paper shadow-2xl sm:rounded-3xl",
          wide ? "sm:max-w-4xl" : "sm:max-w-lg",
        )}
      >
        <div className="flex items-center justify-between gap-4 px-6 pb-2 pt-5">
          <div className="font-display text-xl">{title}</div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X className="size-5" />
          </Button>
        </div>
        <div className="scrollbar-thin overflow-y-auto px-6 pb-6">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

// ---------------- toasts ----------------
type Toast = { id: number; text: string; tone: "ok" | "error" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "error") => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const push = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    const id = next.current++;
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 6000 : 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-6">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={cx(
                "fade-in pointer-events-auto flex max-w-md items-center gap-2 rounded-full px-4 py-2.5 text-sm shadow-lg",
                t.tone === "ok" ? "bg-ink text-paper" : "bg-danger text-white",
              )}
            >
              {t.tone === "ok" ? <Check className="size-4" /> : <X className="size-4" />}
              {t.text}
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);

// ---------------- formatting ----------------
export function cap(s: string | null | undefined): string {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
}

export function money(v: number | null | undefined, currency?: string | null): string {
  if (v === null || v === undefined) return "";
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: currency || "INR", maximumFractionDigits: v % 1 ? 2 : 0 }).format(v);
  } catch {
    return `${currency || ""} ${v}`;
  }
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function dur(s: number | null | undefined): string {
  if (s === null || s === undefined) return "";
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

export function when(ts: number | null | undefined): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
