import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "@/api/client";
import type { Alert, AlertPage, TriageReport } from "@/api/types";
import { Badge, Card, ConfirmButton, EmptyState, Modal, Skeleton, Spinner } from "@/components/ui";
import {
  classificationLabel, classificationStyle, fmtTime, severityLabel, severityStyle,
  statusLabel, statusStyle, toolLabel,
} from "@/lib/utils";
import { errMsg, useUi } from "@/stores/ui";
import { useAuth } from "@/stores/auth";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

export default function Alerts() {
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["alerts", status, severity, q, page],
    queryFn: () => api.get<AlertPage>(`/api/v1/alerts${qs({ status, severity, q, limit: PAGE_SIZE, offset: page * PAGE_SIZE })}`),
  });

  const pages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">告警中心</h1>
          <p className="text-xs text-slate-500">AI 自动研判 · 人工确认闭环</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input className="input !w-52" placeholder="搜索标题…" value={q}
            onChange={(e) => { setQ(e.target.value); setPage(0); }} aria-label="搜索告警" />
          <select className="input !w-32" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} aria-label="按状态筛选">
            <option value="">全部状态</option>
            {Object.entries(statusLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select className="input !w-28" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(0); }} aria-label="按级别筛选">
            <option value="">全部级别</option>
            {Object.entries(severityLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>

      <Card className="!p-0">
        {isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState title="没有符合条件的告警" hint="调整筛选条件，或等待告警接入" icon="🛰️" />
        ) : (
          <div className="divide-y divide-ink-700/50">
            {data.items.map((a) => (
              <button key={a.id} onClick={() => setSelected(a.id)}
                className="flex w-full items-center gap-4 px-5 py-3.5 text-left transition hover:bg-ink-800/60">
                <Badge className={severityStyle[a.severity]}>{severityLabel[a.severity]}</Badge>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-slate-100">{a.title}</span>
                    {a.degraded && <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-300">规则降级</Badge>}
                  </div>
                  <div className="mt-0.5 flex gap-3 font-mono text-[11px] text-slate-500">
                    <span>{a.source}</span>
                    <span>{a.alert_type}</span>
                    {a.src_ip && <span>{a.src_ip}</span>}
                    <span>{fmtTime(a.occurred_at)}</span>
                  </div>
                </div>
                <Badge className={statusStyle[a.status]}>{statusLabel[a.status] ?? a.status}</Badge>
              </button>
            ))}
          </div>
        )}
      </Card>

      {pages > 1 && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>共 {data?.total ?? 0} 条</span>
          <div className="flex gap-2">
            <button className="btn-ghost !px-2.5 !py-1" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>上一页</button>
            <span className="px-2 py-1.5">{page + 1} / {pages}</span>
            <button className="btn-ghost !px-2.5 !py-1" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>下一页</button>
          </div>
        </div>
      )}

      {selected && <AlertDetail alertId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function AlertDetail({ alertId, onClose }: { alertId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useUi();
  const { user } = useAuth();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const canWrite = !!user && (user.roles.includes("analyst") || user.roles.includes("admin"));

  const { data: alert } = useQuery({
    queryKey: ["alert", alertId],
    queryFn: () => api.get<Alert & { triage: TriageReport["result"] }>(`/api/v1/alerts/${alertId}`),
  });
  const { data: report } = useQuery({
    queryKey: ["triage", alertId],
    queryFn: () => api.get<TriageReport>(`/api/v1/alerts/${alertId}/triage`),
  });

  const confirm = useMutation({
    mutationFn: (body: { verdict: string; reason: string }) =>
      api.post(`/api/v1/alerts/${alertId}/confirm`, body),
    onSuccess: () => {
      toast("success", "确认已记录，反馈进入采纳率统计");
      setConfirmOpen(false);
      qc.invalidateQueries({ queryKey: ["alert", alertId] });
      qc.invalidateQueries({ queryKey: ["triage", alertId] });
      qc.invalidateQueries({ queryKey: ["alerts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });

  const retry = useMutation({
    mutationFn: () => api.post(`/api/v1/alerts/${alertId}/retry-triage`),
    onSuccess: () => {
      toast("success", "已重新发起 AI 研判");
      qc.invalidateQueries({ queryKey: ["alert", alertId] });
      qc.invalidateQueries({ queryKey: ["triage", alertId] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-sm"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="h-full w-full max-w-2xl overflow-y-auto border-l border-ink-700 bg-ink-900 p-6 shadow-2xl max-sm:max-w-full">
        {!alert ? (
          <div className="space-y-3">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Badge className={severityStyle[alert.severity]}>{severityLabel[alert.severity]}</Badge>
                  <Badge className={statusStyle[alert.status]}>{statusLabel[alert.status] ?? alert.status}</Badge>
                  {alert.degraded && <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-300">规则降级</Badge>}
                </div>
                <h2 className="mt-2 text-base font-semibold text-white">{alert.title}</h2>
                {alert.description && <p className="mt-1 text-sm text-slate-400">{alert.description}</p>}
              </div>
              <button onClick={onClose} aria-label="关闭" className="rounded-md p-1 text-slate-400 hover:bg-ink-800 hover:text-white">✕</button>
            </div>

            <div className="grid grid-cols-2 gap-3 rounded-xl border border-ink-700/70 p-4 font-mono text-xs text-slate-400 max-sm:grid-cols-1">
              <div>来源：{alert.source} <span className="text-slate-600">/</span> {alert.external_id}</div>
              <div>类型：{alert.alert_type}</div>
              <div>源 IP：{alert.src_ip ?? "—"}</div>
              <div>账号：{alert.user_account ?? "—"}</div>
              <div>发生时间：{fmtTime(alert.occurred_at)}</div>
              <div>确认：{alert.confirmed_as ?? "—"}</div>
            </div>

            {/* AI triage verdict */}
            <section>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-300">
                🧠 AI 研判结论
                {report?.run && (
                  <span className="font-mono text-[10px] text-slate-600">
                    {report.run.model_key} · {report.run.total_prompt_tokens + report.run.total_completion_tokens} tokens · ${report.run.total_cost_usd.toFixed(5)}
                  </span>
                )}
              </h3>
              {!report?.result ? (
                <Card><EmptyState title="尚无研判结论" icon="⏳" /></Card>
              ) : (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge className={classificationStyle[report.result.classification]}>
                      {classificationLabel[report.result.classification]}
                    </Badge>
                    <Badge className={severityStyle[report.result.severity as keyof typeof severityStyle]}>
                      定级 {severityLabel[report.result.severity as keyof typeof severityStyle]}
                    </Badge>
                    <span className="text-xs text-slate-400">置信度 {report.result.confidence}%</span>
                  </div>
                  <Card className="!p-4 text-sm leading-relaxed text-slate-300">{report.result.reasoning}</Card>
                  <div>
                    <div className="mb-1.5 text-xs font-medium text-slate-400">证据链</div>
                    <ul className="space-y-1.5">
                      {report.result.evidence.map((e, i) => (
                        <li key={i} className="rounded-lg border border-ink-700/60 bg-ink-850 px-3 py-2 text-xs">
                          <Badge className="mr-2 border-sky-500/30 bg-sky-500/10 text-sky-300">{e.source}</Badge>
                          <span className="text-slate-300">{e.detail}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  {report.result.recommended_actions.length > 0 && (
                    <div>
                      <div className="mb-1.5 text-xs font-medium text-slate-400">建议处置（需人工批准）</div>
                      {report.result.recommended_actions.map((a, i) => (
                        <div key={i} className="mb-1.5 rounded-lg border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-xs text-slate-300">
                          <span className="font-mono text-violet-300">{a.action}</span>
                          {a.target && <span className="font-mono"> → {a.target}</span>}
                          <span className="text-slate-500"> · {a.reason}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* replay steps */}
            {report && report.steps.length > 0 && (
              <section>
                <h3 className="mb-2 text-sm font-medium text-slate-300">🔍 研判过程回放（{report.steps.length} 步）</h3>
                <ol className="space-y-2">
                  {report.steps.map((s) => (
                    <li key={s.step_no} className="rounded-lg border border-ink-700/60 bg-ink-850 p-3 text-xs">
                      <div className="flex items-center gap-2">
                        <span className="grid h-5 w-5 place-items-center rounded-md bg-gradient-to-br from-sky-500/40 to-violet-500/40 font-mono text-[10px] text-white">{s.step_no}</span>
                        {s.tool ? (
                          <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-300">{toolLabel[s.tool] ?? s.tool}</Badge>
                        ) : (
                          <Badge className="border-violet-500/30 bg-violet-500/10 text-violet-300">{s.kind}</Badge>
                        )}
                      </div>
                      {s.thought && <p className="mt-2 text-slate-400">{s.thought}</p>}
                      {s.tool_args && Object.keys(s.tool_args).length > 0 && (
                        <pre className="mt-1.5 overflow-x-auto rounded bg-ink-950 p-2 font-mono text-[10px] text-slate-500">{JSON.stringify(s.tool_args)}</pre>
                      )}
                      {s.tool_error && <p className="mt-1.5 text-red-400">⚠ {s.tool_error}</p>}
                      {s.tool_result && (
                        <pre className="mt-1.5 max-h-32 overflow-auto rounded bg-ink-950 p-2 font-mono text-[10px] text-slate-500">{JSON.stringify(s.tool_result, null, 1)}</pre>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}

            {/* actions */}
            {canWrite && (
              <div className="flex gap-2 border-t border-ink-700/70 pt-4">
                {alert.status === "triaged" && (
                  <button className="btn-primary flex-1" onClick={() => setConfirmOpen(true)}>确认研判结果</button>
                )}
                {alert.status === "triage_failed" && (
                  <ConfirmButton className="btn-primary flex-1" confirmText="重新发起 AI 研判？"
                    onConfirm={() => retry.mutate()}>
                    {retry.isPending ? <Spinner /> : "重试 AI 研判"}
                  </ConfirmButton>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <ConfirmModal open={confirmOpen} onClose={() => setConfirmOpen(false)}
        current={report?.result ?? null}
        onSubmit={(body) => confirm.mutate(body)}
        busy={confirm.isPending} />
    </div>
  );
}

function ConfirmModal({
  open, onClose, current, onSubmit, busy,
}: {
  open: boolean; onClose: () => void; current: TriageReport["result"];
  onSubmit: (body: { verdict: string; reason: string }) => void; busy: boolean;
}) {
  const [verdict, setVerdict] = useState<"" | "true_positive" | "false_positive">("");
  const [reason, setReason] = useState("");
  const aiClass = current?.classification;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!verdict || reason.trim().length < 3) return;
    onSubmit({ verdict, reason });
  }

  return (
    <Modal open={open} onClose={onClose} title="确认告警研判结果">
      <form onSubmit={submit} className="space-y-4">
        {aiClass && (
          <div className="rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slate-400">
            AI 结论：<Badge className={classificationStyle[aiClass]}>{classificationLabel[aiClass]}</Badge>
            {" "}你的确认将与其对比，进入采纳率统计。
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          {(["true_positive", "false_positive"] as const).map((v) => (
            <button type="button" key={v} onClick={() => setVerdict(v)}
              className={cn("rounded-xl border px-4 py-3 text-sm font-medium transition",
                verdict === v
                  ? v === "true_positive" ? "border-red-500 bg-red-500/15 text-red-200" : "border-emerald-500 bg-emerald-500/15 text-emerald-200"
                  : "border-ink-600 text-slate-400 hover:border-slate-500")}>
              {v === "true_positive" ? "🚨 真实安全事件" : "✅ 误报 / 良性"}
            </button>
          ))}
        </div>
        <div>
          <label className="label" htmlFor="reason">确认理由（必填，进入审计与统计）</label>
          <textarea id="reason" className="input min-h-20" value={reason}
            onChange={(e) => setReason(e.target.value)} placeholder="例如：已核实攻击源并复现成功登录…" />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>取消</button>
          <button type="submit" className="btn-primary" disabled={!verdict || reason.trim().length < 3 || busy}>
            {busy ? <Spinner /> : "提交确认"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
