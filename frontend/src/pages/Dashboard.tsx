import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Dashboard as DashboardData } from "@/api/types";
import { Card, Skeleton, Stat, EmptyState } from "@/components/ui";
import { fmtPct, statusLabel } from "@/lib/utils";

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get<DashboardData>("/api/v1/analytics/dashboard"),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (error || !data) return <EmptyState title="看板加载失败" hint="请检查后端服务状态" icon="⚠️" />;

  const maxStatus = Math.max(1, ...data.alerts_by_status.map((s) => s.count));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">安全运营工作台</h1>
        <p className="text-xs text-slate-500">全部指标来自真实业务数据 · 最近 30 天</p>
      </div>

      <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2 max-sm:grid-cols-1">
        <Stat label="告警总量" value={data.alerts_total} sub="接入告警总数" />
        <Stat label="AI 降噪率" value={fmtPct(data.noise_reduction_rate)} sub="确认误报 / 已确认告警" accent />
        <Stat label="AI 采纳率" value={fmtPct(data.ai_adoption_rate)} sub="人工确认与 AI 一致比例" accent />
        <Stat label="平均处置时长" value={data.mttr_hours === null ? "—" : `${data.mttr_hours}h`} sub="事件中位 MTTR" />
      </div>

      <div className="grid grid-cols-3 gap-4 max-lg:grid-cols-1">
        <Card className="col-span-2">
          <h3 className="mb-4 text-sm font-medium text-slate-300">告警漏斗（状态分布）</h3>
          {data.alerts_by_status.length === 0 ? (
            <EmptyState title="暂无告警" hint="通过 POST /api/v1/alerts/ingest/alerts 接入告警" icon="🛰️" />
          ) : (
            <div className="space-y-2.5">
              {data.alerts_by_status.map((s) => (
                <div key={s.status} className="flex items-center gap-3">
                  <span className="w-20 shrink-0 text-xs text-slate-400">{statusLabel[s.status] ?? s.status}</span>
                  <div className="h-5 flex-1 overflow-hidden rounded-md bg-ink-800">
                    <div className="h-full rounded-md bg-gradient-to-r from-sky-500/70 to-violet-500/70"
                      style={{ width: `${(s.count / maxStatus) * 100}%` }} />
                  </div>
                  <span className="w-8 text-right font-mono text-xs text-slate-300">{s.count}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card>
            <h3 className="mb-3 text-sm font-medium text-slate-300">待人工确认</h3>
            <div className="flex items-end gap-2">
              <span className="text-3xl font-semibold text-teal-300">{data.triaged_pending_confirmation}</span>
              <span className="pb-1 text-xs text-slate-500">条已研判告警等待确认</span>
            </div>
          </Card>
          <Card>
            <h3 className="mb-3 text-sm font-medium text-slate-300">LLM 成本（30 天）</h3>
            <div className="flex items-end gap-2">
              <span className="font-mono text-2xl font-semibold text-violet-300">${data.llm_cost_usd_total.toFixed(4)}</span>
              <span className="pb-1 text-xs text-slate-500">{data.llm_calls_total} 次调用</span>
            </div>
            <p className="mt-2 text-[11px] text-slate-600">每次模型调用逐条记账，按模型/日期可下钻</p>
          </Card>
        </div>
      </div>
    </div>
  );
}
