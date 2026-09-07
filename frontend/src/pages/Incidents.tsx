import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "@/api/client";
import type { Comment, Incident, Task } from "@/api/types";
import { Badge, Card, EmptyState, Modal, Skeleton, Spinner } from "@/components/ui";
import { cn, fmtTime, incidentStatusLabel, severityLabel, severityStyle } from "@/lib/utils";
import { errMsg, useUi } from "@/stores/ui";
import { useAuth } from "@/stores/auth";

const FLOW = ["new", "investigating", "contained", "eradicated", "recovered", "closed"];

export default function Incidents() {
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["incidents", status],
    queryFn: () => api.get<Incident[]>(`/api/v1/incidents${qs({ status, limit: 50 })}`),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">事件中心</h1>
          <p className="text-xs text-slate-500">PICERL 状态机流转 · 任务与评论协作</p>
        </div>
        <div className="flex gap-2">
          <select className="input !w-32" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="按状态筛选">
            <option value="">全部状态</option>
            {Object.entries(incidentStatusLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button className="btn-primary" onClick={() => setCreateOpen(true)}>+ 创建事件</button>
        </div>
      </div>

      <Card className="!p-0">
        {isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        ) : !data || data.length === 0 ? (
          <EmptyState title="暂无事件" hint="在告警详情中将确认的真实告警升级为事件" icon="📁" />
        ) : (
          <div className="divide-y divide-ink-700/50">
            {data.map((inc) => (
              <button key={inc.id} onClick={() => setSelected(inc.id)}
                className="flex w-full items-center gap-4 px-5 py-3.5 text-left transition hover:bg-ink-800/60">
                <Badge className={severityStyle[inc.severity]}>{severityLabel[inc.severity]}</Badge>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-100">{inc.title}</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">
                    开始于 {fmtTime(inc.created_at)}
                    {inc.reopened_count > 0 && <span className="ml-2 text-amber-400">重开 {inc.reopened_count} 次</span>}
                  </div>
                </div>
                <IncidentFlow status={inc.status} />
              </button>
            ))}
          </div>
        )}
      </Card>

      {selected && <IncidentDetail id={selected} onClose={() => setSelected(null)} />}
      <CreateIncident open={createOpen} onClose={() => setCreateOpen(false)} onCreated={(id) => setSelected(id)} />
    </div>
  );
}

function IncidentFlow({ status }: { status: string }) {
  const idx = FLOW.indexOf(status === "reopened" ? "investigating" : status);
  return (
    <div className="hidden items-center gap-1 md:flex" aria-label={`状态 ${incidentStatusLabel[status]}`}>
      {FLOW.map((s, i) => (
        <div key={s} title={incidentStatusLabel[s]}
          className={cn("h-1.5 w-8 rounded-full",
            i < idx ? "bg-sky-500/70" : i === idx ? (status === "closed" ? "bg-emerald-500" : "bg-violet-400 animate-pulse") : "bg-ink-700")} />
      ))}
      <span className="ml-2 w-14 text-right text-[11px] text-slate-400">{incidentStatusLabel[status]}</span>
    </div>
  );
}

const NEXT: Record<string, { to: string; label: string; needSummary?: boolean }[]> = {
  new: [{ to: "investigating", label: "开始调查" }],
  investigating: [{ to: "contained", label: "标记已遏制" }],
  contained: [{ to: "eradicated", label: "标记已根除" }, { to: "investigating", label: "退回调查" }],
  eradicated: [{ to: "recovered", label: "确认恢复" }, { to: "investigating", label: "退回调查" }],
  recovered: [{ to: "closed", label: "关闭事件", needSummary: true }, { to: "investigating", label: "退回调查" }],
  closed: [{ to: "reopened", label: "重开事件" }],
  reopened: [{ to: "investigating", label: "开始调查" }],
};

function IncidentDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { toast } = useUi();
  const { user } = useAuth();
  const canWrite = !!user && (user.roles.includes("analyst") || user.roles.includes("admin"));

  const { data: inc } = useQuery({ queryKey: ["incident", id], queryFn: () => api.get<Incident>(`/api/v1/incidents/${id}`) });
  const { data: tasks } = useQuery({ queryKey: ["incident", id, "tasks"], queryFn: () => api.get<Task[]>(`/api/v1/incidents/${id}/tasks`) });
  const { data: comments } = useQuery({ queryKey: ["incident", id, "comments"], queryFn: () => api.get<Comment[]>(`/api/v1/incidents/${id}/comments`) });

  const transition = useMutation({
    mutationFn: (body: { to_status: string; reason: string; close_summary?: string }) =>
      api.post(`/api/v1/incidents/${id}/transition`, body),
    onSuccess: () => {
      toast("success", "状态已流转");
      qc.invalidateQueries({ queryKey: ["incident"] });
      qc.invalidateQueries({ queryKey: ["incidents"] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="h-full w-full max-w-2xl overflow-y-auto border-l border-ink-700 bg-ink-900 p-6 shadow-2xl max-sm:max-w-full">
        {!inc ? (
          <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Badge className={severityStyle[inc.severity]}>{severityLabel[inc.severity]}</Badge>
                  <Badge className="border-sky-500/30 bg-sky-500/10 text-sky-300">{incidentStatusLabel[inc.status]}</Badge>
                </div>
                <h2 className="mt-2 text-base font-semibold text-white">{inc.title}</h2>
                {inc.description && <p className="mt-1 text-sm text-slate-400">{inc.description}</p>}
              </div>
              <button onClick={onClose} aria-label="关闭" className="rounded-md p-1 text-slate-400 hover:bg-ink-800 hover:text-white">✕</button>
            </div>

            {canWrite && (
              <div className="flex flex-wrap gap-2">
                {(NEXT[inc.status] ?? []).map((n) => (
                  <TransitionButton key={n.to} next={n} onGo={(reason, close_summary) => transition.mutate({ to_status: n.to, reason, close_summary })} />
                ))}
              </div>
            )}

            <TaskSection incidentId={id} tasks={tasks ?? []} canWrite={canWrite} />
            <CommentSection incidentId={id} comments={comments ?? []} canWrite={canWrite} />
          </div>
        )}
      </div>
    </div>
  );
}

function TransitionButton({ next, onGo }: { next: { to: string; label: string; needSummary?: boolean }; onGo: (reason: string, summary?: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [summary, setSummary] = useState("");
  return (
    <>
      <button className={next.to === "closed" ? "btn-primary" : "btn-ghost"} onClick={() => setOpen(true)}>{next.label}</button>
      <Modal open={open} onClose={() => setOpen(false)} title={next.label}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (reason.trim().length >= 3) { onGo(reason, next.needSummary ? summary : undefined); setOpen(false); } }}>
          <div>
            <label className="label" htmlFor="tr">流转理由（必填，写入审计）</label>
            <input id="tr" className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          {next.needSummary && (
            <div>
              <label className="label" htmlFor="cs">关闭总结（必填）</label>
              <textarea id="cs" className="input min-h-20" value={summary} onChange={(e) => setSummary(e.target.value)} />
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>取消</button>
            <button type="submit" className="btn-primary" disabled={reason.trim().length < 3 || (next.needSummary && !summary.trim())}>确认流转</button>
          </div>
        </form>
      </Modal>
    </>
  );
}

function TaskSection({ incidentId, tasks, canWrite }: { incidentId: string; tasks: Task[]; canWrite: boolean }) {
  const qc = useQueryClient();
  const { toast } = useUi();
  const [title, setTitle] = useState("");

  const create = useMutation({
    mutationFn: () => api.post(`/api/v1/incidents/${incidentId}/tasks`, { title }),
    onSuccess: () => { setTitle(""); qc.invalidateQueries({ queryKey: ["incident", incidentId, "tasks"] }); },
    onError: (e) => toast("error", errMsg(e)),
  });
  const move = useMutation({
    mutationFn: ({ taskId, to }: { taskId: string; to: string }) =>
      api.post(`/api/v1/incidents/tasks/${taskId}/transition`, { to_status: to, reason: "页面快捷操作" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["incident", incidentId, "tasks"] }),
    onError: (e) => toast("error", errMsg(e)),
  });

  const taskNext: Record<string, { to: string; label: string }[]> = {
    todo: [{ to: "in_progress", label: "开始" }, { to: "cancelled", label: "取消" }],
    in_progress: [{ to: "done", label: "完成" }, { to: "blocked", label: "阻塞" }],
    blocked: [{ to: "in_progress", label: "恢复" }],
  };

  return (
    <section>
      <h3 className="mb-2 text-sm font-medium text-slate-300">📋 处置任务（{tasks.length}）</h3>
      <div className="space-y-2">
        {tasks.length === 0 && <p className="text-xs text-slate-600">暂无任务</p>}
        {tasks.map((t) => (
          <div key={t.id} className="flex items-center gap-3 rounded-lg border border-ink-700/60 bg-ink-850 px-3 py-2.5">
            <span className={cn("text-xs font-medium",
              t.status === "done" ? "text-emerald-300 line-through" : t.status === "blocked" ? "text-red-300" : "text-slate-200")}>
              {t.title}
            </span>
            <Badge className="ml-auto border-ink-600 text-slate-400">{t.status}</Badge>
            {canWrite && taskNext[t.status]?.map((n) => (
              <button key={n.to} className="text-[11px] text-sky-400 hover:text-sky-300"
                onClick={() => move.mutate({ taskId: t.id, to: n.to })}>{n.label}</button>
            ))}
          </div>
        ))}
        {canWrite && (
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate(); }}>
            <input className="input flex-1" placeholder="新任务标题…" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="新任务标题" />
            <button className="btn-ghost" disabled={!title.trim() || create.isPending}>{create.isPending ? <Spinner /> : "添加"}</button>
          </form>
        )}
      </div>
    </section>
  );
}

function CommentSection({ incidentId, comments, canWrite }: { incidentId: string; comments: Comment[]; canWrite: boolean }) {
  const qc = useQueryClient();
  const { toast } = useUi();
  const [body, setBody] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/api/v1/incidents/${incidentId}/comments`, { body }),
    onSuccess: () => { setBody(""); qc.invalidateQueries({ queryKey: ["incident", incidentId, "comments"] }); },
    onError: (e) => toast("error", errMsg(e)),
  });
  return (
    <section>
      <h3 className="mb-2 text-sm font-medium text-slate-300">💬 协作评论（{comments.length}）</h3>
      <div className="space-y-2">
        {comments.map((c) => (
          <div key={c.id} className="rounded-lg border border-ink-700/60 bg-ink-850 px-3 py-2.5 text-sm text-slate-300">
            {c.body}
            <div className="mt-1 text-[10px] text-slate-600">{fmtTime(c.created_at)}</div>
          </div>
        ))}
        {canWrite && (
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); if (body.trim()) add.mutate(); }} className="flex gap-2">
            <input className="input flex-1" placeholder="添加评论…" value={body} onChange={(e) => setBody(e.target.value)} aria-label="评论内容" />
            <button className="btn-ghost" disabled={!body.trim() || add.isPending}>{add.isPending ? <Spinner /> : "发送"}</button>
          </form>
        )}
      </div>
    </section>
  );
}

function CreateIncident({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const { toast } = useUi();
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("high");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<Incident>("/api/v1/incidents", { title, severity, description }),
    onSuccess: (inc) => {
      toast("success", "事件已创建");
      qc.invalidateQueries({ queryKey: ["incidents"] });
      onClose(); setTitle(""); setDescription("");
      onCreated(inc.id);
    },
    onError: (e) => toast("error", errMsg(e)),
  });
  return (
    <Modal open={open} onClose={onClose} title="创建安全事件">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create.mutate(); }}>
        <div>
          <label className="label" htmlFor="it">事件标题</label>
          <input id="it" className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="is">级别</label>
          <select id="is" className="input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {Object.entries(severityLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="id">描述</label>
          <textarea id="id" className="input min-h-20" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>取消</button>
          <button type="submit" className="btn-primary" disabled={!title.trim() || create.isPending}>{create.isPending ? <Spinner /> : "创建"}</button>
        </div>
      </form>
    </Modal>
  );
}
