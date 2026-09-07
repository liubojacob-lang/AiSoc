import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { AskResponse, KbDocument } from "@/api/types";
import { Badge, Card, EmptyState, Skeleton, Spinner } from "@/components/ui";
import { cn, fmtBytes, fmtTime } from "@/lib/utils";
import { errMsg, useUi } from "@/stores/ui";
import { useAuth } from "@/stores/auth";

export default function Knowledge() {
  const { user } = useAuth();
  const canWrite = !!user && (user.roles.includes("analyst") || user.roles.includes("admin"));
  const qc = useQueryClient();
  const { toast } = useUi();
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: docs, isLoading } = useQuery({
    queryKey: ["kb"],
    queryFn: () => api.get<KbDocument[]>("/api/v1/kb/documents"),
  });

  const [question, setQuestion] = useState("");
  const ask = useMutation({
    mutationFn: (q: string) => api.post<AskResponse>("/api/v1/kb/ask", { question: q }),
    onError: (e) => toast("error", errMsg(e)),
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.upload<KbDocument>("/api/v1/kb/documents", file, file.name.replace(/\.[^.]+$/, "")),
    onSuccess: (d) => {
      toast("success", `文档已上传并完成索引（${d.chunk_count} 个切片）`);
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/kb/documents/${id}`),
    onSuccess: () => { toast("success", "文档已删除"); qc.invalidateQueries({ queryKey: ["kb"] }); },
    onError: (e) => toast("error", errMsg(e)),
  });

  return (
    <div className="grid grid-cols-[1fr_400px] gap-5 max-lg:grid-cols-1">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-white">安全知识库</h1>
            <p className="text-xs text-slate-500">Playbook 与预案 · RAG 检索增强，答案强制引用溯源</p>
          </div>
          {canWrite && (
            <>
              <input ref={fileRef} type="file" accept=".md,.txt" className="hidden"
                onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} aria-label="选择文档" />
              <button className="btn-primary" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
                {upload.isPending ? <Spinner /> : "上传文档"}
              </button>
            </>
          )}
        </div>

        <Card className="!p-0">
          {isLoading ? (
            <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : !docs || docs.length === 0 ? (
            <EmptyState title="知识库还是空的" hint="上传 Markdown/TXT 格式的 Playbook 开始构建" icon="📚" />
          ) : (
            <div className="divide-y divide-ink-700/50">
              {docs.map((d) => (
                <div key={d.id} className="flex items-center gap-3 px-5 py-3.5">
                  <span className="text-xl" aria-hidden>{d.status === "indexed" ? "📄" : d.status === "failed" ? "⚠️" : "⏳"}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-slate-100">{d.title}</div>
                    <div className="font-mono text-[11px] text-slate-500">
                      {d.chunk_count} 切片 · {fmtBytes(d.size_bytes)} · {fmtTime(d.created_at)}
                      {d.error && <span className="ml-2 text-red-400">{d.error}</span>}
                    </div>
                  </div>
                  <Badge className={cn(d.status === "indexed" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : d.status === "failed" ? "border-red-500/30 bg-red-500/10 text-red-300" : "border-slate-500/30 text-slate-400")}>
                    {d.status}
                  </Badge>
                  {canWrite && (
                    <button className="text-xs text-slate-500 hover:text-red-300"
                      onClick={() => window.confirm(`删除文档「${d.title}」？`) && remove.mutate(d.id)}>删除</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Ask panel */}
      <Card className="flex h-[calc(100vh-8rem)] flex-col">
        <h3 className="text-sm font-medium text-slate-300">🤖 知识库问答</h3>
        <p className="mt-1 text-[11px] text-slate-600">基于已索引文档回答，结论必须携带 [n] 引用</p>

        <div className="mt-4 flex-1 space-y-3 overflow-y-auto pr-1">
          {!ask.data && !ask.isPending && (
            <div className="rounded-xl border border-dashed border-ink-600 p-4 text-xs leading-relaxed text-slate-500">
              试试问：
              <br />· brute force 事件的处置步骤是什么？
              <br />· 发现恶意进程后第一步做什么？
            </div>
          )}
          {ask.isPending && <Skeleton className="h-24" />}
          {ask.data && (
            <>
              {ask.data.degraded && (
                <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                  LLM 暂不可用，以下为直接检索到的原文片段
                </div>
              )}
              <div className="whitespace-pre-wrap rounded-xl border border-ink-700 bg-ink-850 p-4 text-sm leading-relaxed text-slate-200">
                {ask.data.answer}
              </div>
              {ask.data.citations.length > 0 && (
                <div>
                  <div className="mb-1.5 text-xs font-medium text-slate-400">引用来源</div>
                  {ask.data.citations.map((c, i) => (
                    <div key={i} className="mb-1.5 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2 text-xs">
                      <span className="mr-2 font-mono text-sky-300">[{i + 1}]</span>
                      {c.document_title}
                      {c.heading && <span className="text-slate-500"> · {c.heading}</span>}
                      <span className="ml-2 font-mono text-slate-600">score {c.score}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <form className="mt-3 flex gap-2 border-t border-ink-700/70 pt-3"
          onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 3) ask.mutate(question.trim()); }}>
          <input className="input flex-1" placeholder="向知识库提问…" value={question}
            onChange={(e) => setQuestion(e.target.value)} aria-label="问题" />
          <button className="btn-primary" disabled={question.trim().length < 3 || ask.isPending}>
            {ask.isPending ? <Spinner /> : "提问"}
          </button>
        </form>
      </Card>
    </div>
  );
}
