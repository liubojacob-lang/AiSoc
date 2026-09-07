/** 基础 UI 组件（shadcn 风格，自建以保持现代观感与可控性）。 */
import { ReactNode, useEffect } from "react";
import { cn } from "@/lib/utils";
import { useUi } from "@/stores/ui";

export function Badge({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", className)}>
      {children}
    </span>
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("card p-5", className)}>{children}</div>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-ink-700/60", className)} />;
}

export function EmptyState({ title, hint, icon = "📭" }: { title: string; hint?: string; icon?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
      <div className="text-4xl" aria-hidden>{icon}</div>
      <div className="text-sm font-medium text-slate-300">{title}</div>
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cn("h-4 w-4 animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-label="加载中">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function Modal({
  open, onClose, title, children, wide,
}: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh] backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title}
        className={cn("card w-full p-6 shadow-2xl", wide ? "max-w-3xl" : "max-w-md")}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">{title}</h3>
          <button onClick={onClose} aria-label="关闭" className="rounded-md p-1 text-slate-400 hover:bg-ink-800 hover:text-white">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ToastHost() {
  const { toasts, dismiss } = useUi();
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-80 flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((t) => (
        <button key={t.id} onClick={() => dismiss(t.id)}
          className={cn(
            "pointer-events-auto rounded-lg border px-4 py-3 text-left text-sm shadow-xl backdrop-blur",
            t.kind === "success" && "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
            t.kind === "error" && "border-red-500/40 bg-red-500/10 text-red-200",
            t.kind === "info" && "border-sky-500/40 bg-sky-500/10 text-sky-200",
          )}>
          {t.message}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: string; accent?: boolean }) {
  return (
    <Card className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <span className={cn("text-2xl font-semibold", accent && "bg-gradient-to-r from-sky-400 to-violet-400 bg-clip-text text-transparent")}>
        {value}
      </span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </Card>
  );
}

export function ConfirmButton({
  onConfirm, children, className, confirmText = "确认执行该操作？",
}: { onConfirm: () => void; children: ReactNode; className?: string; confirmText?: string }) {
  return (
    <button
      className={className}
      onClick={(e) => {
        e.stopPropagation();
        if (window.confirm(confirmText)) onConfirm();
      }}
    >
      {children}
    </button>
  );
}
