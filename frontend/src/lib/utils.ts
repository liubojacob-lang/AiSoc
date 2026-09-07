import type { Severity } from "@/api/types";

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

export const severityStyle: Record<Severity, string> = {
  low: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  high: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  critical: "bg-red-500/15 text-red-300 border-red-500/30",
};

export const severityLabel: Record<Severity, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

export const statusLabel: Record<string, string> = {
  new: "待研判",
  triaging: "研判中",
  triaged: "已研判",
  confirmed_true: "确认真实",
  incident_created: "已建事件",
  confirmed_false: "确认误报",
  triage_failed: "研判失败",
};

export const statusStyle: Record<string, string> = {
  new: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  triaging: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  triaged: "bg-teal-500/15 text-teal-300 border-teal-500/30",
  confirmed_true: "bg-orange-500/15 text-orange-300 border-orange-500/30",
  incident_created: "bg-red-500/15 text-red-300 border-red-500/30",
  confirmed_false: "bg-slate-500/15 text-slate-300 border-slate-500/30",
  triage_failed: "bg-red-500/20 text-red-300 border-red-500/40",
};

export const classificationLabel: Record<string, string> = {
  true_positive: "真实攻击",
  false_positive: "误报",
  suspicious: "可疑",
  needs_investigation: "需人工排查",
};

export const classificationStyle: Record<string, string> = {
  true_positive: "bg-red-500/15 text-red-300 border-red-500/30",
  false_positive: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  suspicious: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  needs_investigation: "bg-sky-500/15 text-sky-300 border-sky-500/30",
};

export const incidentStatusLabel: Record<string, string> = {
  new: "新建",
  investigating: "调查中",
  contained: "已遏制",
  eradicated: "已根除",
  recovered: "已恢复",
  closed: "已关闭",
  reopened: "已重开",
};

export const toolLabel: Record<string, string> = {
  query_threat_intel: "威胁情报查询",
  query_asset: "资产查询",
  search_similar_alerts: "历史相似告警",
  search_knowledge: "知识库检索",
  list_alert_context: "告警上下文",
  propose_action: "处置建议",
};
