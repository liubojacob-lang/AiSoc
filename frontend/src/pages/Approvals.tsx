import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ActionApproval } from "@/api/types";
import { Badge, Card, EmptyState, Modal, Skeleton } from "@/components/ui";
import { cn, fmtTime } from "@/lib/utils";
import { errMsg, useUi } from "@/stores/ui";
import { useAuth } from "@/stores/auth";

const STATUS_STYLE: Record<string, string> = {
  proposed: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  approved_l1: "border-violet-500/30 bg-violet-500/10 text-violet-300",
  approved: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  rejected: "border-slate-500/30 bg-slate-500/10 text-slate-400",
  executed: "border-emerald-500/40 bg-emerald-500/15 text-emerald-200",
  execution_failed: "border-red-500/40 bg-red-500/10 text-red-300",
  cancelled: "border-slate-600 text-slate-500",
};
const STATUS_LABEL: Record<string, string> = {
  proposed: "待 L1",
  approved_l1: "待 L2（管理员）",
  approved: "已双批 · 待执行",
  rejected: "已驳回",
  executed: "已执行",
  execution_failed: "执行失败（可重试）",
  cancelled: "已取消",
};
const ACTION_LABEL: Record<string, string> = {
  block_ip: "封禁 IP",
  block_domain: "封禁域名",
  isolate_host: "隔离主机",
  reset_password: "重置密码",
  disable_account: "禁用账号",
  monitor: "持续监控",
};

const short = (id: string | null) => (id ? id.slice(0, 8) : "—");

export default function Approvals() {
  const qc = useQueryClient();
  const { toast } = useUi();
  const { user } = useAuth();
  const isAdmin = !!user && user.roles.includes("admin");
  const canWrite = !!user && (user.roles.includes("analyst") || isAdmin);
  const [statusFilter, setStatusFilter] = useState("");
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["actions", statusFilter],
    queryFn: () =>
      api.get<ActionApproval[]>(`/api/v1/actions${statusFilter ? `?status=${statusFilter}` : ""}`),
  });

  const act = useMutation({
    mutationFn: ({ id, verb, body }: { id: string; verb: string; body?: unknown }) =>
      api.post(`/api/v1/actions/${id}/${verb}`, body),
    onSuccess: () => {
      toast("success", "操作已记录并审计");
      setRejectId(null);
      setRejectReason("");
      qc.invalidateQueries({ queryKey: ["actions"] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">处置审批</h1>
          <p className="text-xs text-slate-500">
            双人规则：L1 分析师批准 → L2 管理员批准（不可同一人）→ 执行 · 全程审计
          </p>
        </div>
        <select className="input !w-44" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="按状态筛选">
          <option value="">全部状态</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      <Card className="!p-0">
        {isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : !data || data.length === 0 ? (
          <EmptyState title="没有审批单" hint="在告警详情的「建议处置」中发起审批" icon="✅" />
        ) : (
          <div className="divide-y divide-ink-700/50">
            {data.map((a) => (
              <div key={a.id} className="px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className={STATUS_STYLE[a.status]}>{STATUS_LABEL[a.status] ?? a.status}</Badge>
                  <span className="font-mono text-sm font-medium text-slate-100">
                    {ACTION_LABEL[a.action] ?? a.action}
                  </span>
                  {a.target && <span className="font-mono text-xs text-orange-300">→ {a.target}</span>}
                  <span className="ml-auto font-mono text-[11px] text-slate-600">{fmtTime(a.created_at)}</span>
                </div>
                <p className="mt-1.5 text-xs text-slate-400">{a.reason}</p>
                <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-[10px] text-slate-600">
                  <span>发起 {short(a.proposed_by)}</span>
                  {a.approved_l1_by && <span>L1 {short(a.approved_l1_by)}</span>}
                  {a.approved_l2_by && <span>L2 {short(a.approved_l2_by)}</span>}
                  {a.rejected_reason && <span className="text-red-400">驳回：{a.rejected_reason}</span>}
                  {a.execution_result != null && (
                    <span className="text-emerald-500/80">
                      执行：{a.execution_mode}
                      {typeof a.execution_result.error === "string" && ` · ${a.execution_result.error}`}
                    </span>
                  )}
                </div>
                {canWrite && (
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {a.status === "proposed" && (
                      <>
                        <button className="btn-ghost !py-1.5 text-xs" onClick={() => act.mutate({ id: a.id, verb: "approve" })}>L1 批准</button>
                        <button className="btn-danger !py-1.5 text-xs" onClick={() => setRejectId(a.id)}>驳回</button>
                      </>
                    )}
                    {a.status === "approved_l1" && isAdmin && (
                      <button className="btn-primary !py-1.5 text-xs" onClick={() => act.mutate({ id: a.id, verb: "approve" })}>L2 批准（管理员）</button>
                    )}
                    {a.status === "approved_l1" && !isAdmin && (
                      <span className="text-[11px] text-slate-600">等待管理员 L2 批准</span>
                    )}
                    {a.status === "approved" && isAdmin && (
                      <button className="btn-primary !py-1.5 text-xs" onClick={() => act.mutate({ id: a.id, verb: "execute" })}>执行</button>
                    )}
                    {a.status === "execution_failed" && isAdmin && (
                      <button className="btn-ghost !py-1.5 text-xs" onClick={() => act.mutate({ id: a.id, verb: "execute" })}>重试执行</button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Modal open={!!rejectId} onClose={() => setRejectId(null)} title="驳回处置建议">
        <div className="space-y-3">
          <label className="label" htmlFor="rr">驳回理由（必填，写入审计）</label>
          <textarea id="rr" className="input min-h-20" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} />
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => setRejectId(null)}>取消</button>
            <button
              className={cn("btn-danger")}
              disabled={rejectReason.trim().length < 3}
              onClick={() => rejectId && act.mutate({ id: rejectId, verb: "reject", body: { reason: rejectReason } })}
            >
              确认驳回
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
