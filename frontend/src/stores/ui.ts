import { create } from "zustand";

export interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
}

interface UiState {
  toasts: Toast[];
  toast: (kind: Toast["kind"], message: string) => void;
  dismiss: (id: number) => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
}

let nextId = 1;

export const useUi = create<UiState>((set, get) => ({
  toasts: [],
  toast(kind, message) {
    const id = nextId++;
    set({ toasts: [...get().toasts, { id, kind, message }] });
    setTimeout(() => get().dismiss(id), 4200);
  },
  dismiss(id) {
    set({ toasts: get().toasts.filter((t) => t.id !== id) });
  },
  theme: "dark",
  toggleTheme() {
    const next = get().theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    set({ theme: next });
  },
}));

/** Error → readable message（统一错误体）。 */
export const errMsg = (e: unknown): string => {
  const anyE = e as { message?: string; code?: string };
  return anyE?.message ? `${anyE.message}` : "发生未知错误";
};
