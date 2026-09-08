import { FormEvent, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Badge, Card, EmptyState, Spinner } from "@/components/ui";
import { cn, fmtTime } from "@/lib/utils";
import { errMsg, useUi } from "@/stores/ui";

interface Turn {
  role: "user" | "assistant";
  content: string;
  refs?: { kind: string; title: string; detail: string }[];
  time: string;
}

const SUGGESTIONS = [
  "现在有哪些高危告警？",
  "目前事件的整体情况如何？",
  "平台今天的降噪率是多少？",
  "brute force 的处置步骤是什么？",
];

export default function Assistant() {
  const qc = useQueryClient();
  const { toast } = useUi();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.get<{ id: string; title: string; created_at: string }[]>("/api/v1/ai/conversations"),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, streaming]);

  const ask = useMutation({
    mutationFn: (question: string) =>
      api.post<{ conversation_id: string; answer: string; refs: { kind: string; title: string; detail: string }[]; model_key: string }>(
        "/api/v1/ai/chat",
        { question, conversation_id: conversationId },
      ),
    onMutate: (question) => {
      setTurns((t) => [...t, { role: "user", content: question, time: new Date().toISOString() }]);
      setStreaming(true);
    },
    onSuccess: (data) => {
      setConversationId(data.conversation_id);
      setTurns((t) => [...t, { role: "assistant", content: data.answer, refs: data.refs, time: new Date().toISOString() }]);
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (e) => {
      toast("error", errMsg(e));
      setTurns((t) => [...t, { role: "assistant", content: "（本轮回答失败，请重试）", time: new Date().toISOString() }]);
    },
    onSettled: () => setStreaming(false),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || streaming) return;
    setInput("");
    ask.mutate(q);
  }

  function loadConversation(id: string) {
    setConversationId(id);
    ask.reset();
    api
      .get<{ role: string; content: string; refs: { kind: string; title: string; detail: string }[] | null; created_at: string }[]>(
        `/api/v1/ai/conversations/${id}/messages`,
      )
      .then((msgs) =>
        setTurns(msgs.map((m) => ({ role: m.role as "user" | "assistant", content: m.content, refs: m.refs ?? undefined, time: m.created_at }))),
      )
      .catch(() => toast("error", "会话加载失败"));
  }

  return (
    <div className="grid grid-cols-[1fr_260px] gap-5 max-lg:grid-cols-1">
      <Card className="flex h-[calc(100vh-8rem)] flex-col !p-0">
        <div className="flex items-center justify-between border-b border-ink-700/70 px-5 py-3.5">
          <div>
            <h1 className="text-sm font-semibold text-white">🤖 SOC 助手</h1>
            <p className="text-[11px] text-slate-500">查询告警 / 事件 / 统计 / 知识库 · 每轮对话可审计</p>
          </div>
          <button className="btn-ghost !py-1.5 text-xs"
            onClick={() => { setConversationId(null); setTurns([]); }}>
            + 新会话
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {turns.length === 0 && (
            <div className="space-y-3">
              <EmptyState title="问点什么吧" hint="助手会先调用工具查数据，再基于数据回答" icon="💬" />
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="rounded-full border border-ink-600 px-3 py-1.5 text-xs text-slate-400 transition hover:border-sky-500/50 hover:text-sky-300"
                    onClick={() => { setInput(s); }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} className={cn("flex", t.role === "user" ? "justify-end" : "justify-start")}>
              <div className={cn("max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                t.role === "user"
                  ? "bg-gradient-to-r from-sky-500/80 to-violet-500/80 text-white"
                  : "border border-ink-700 bg-ink-850 text-slate-200")}>
                <div className="whitespace-pre-wrap">{t.content}</div>
                {t.refs && t.refs.length > 0 && (
                  <div className="mt-2.5 space-y-1.5 border-t border-ink-700 pt-2.5">
                    {t.refs.map((r, j) => (
                      <div key={j} className="rounded-lg border border-sky-500/20 bg-sky-500/5 px-2.5 py-1.5 text-[11px]">
                        <Badge className={cn("mr-2",
                          r.kind === "alert" ? "border-orange-500/30 bg-orange-500/10 text-orange-300"
                            : r.kind === "incident" ? "border-red-500/30 bg-red-500/10 text-red-300"
                              : "border-sky-500/30 bg-sky-500/10 text-sky-300")}>
                          {r.kind}
                        </Badge>
                        <span className="text-slate-300">{r.title}</span>
                        <span className="ml-1 text-slate-500">{r.detail}</span>
                      </div>
                    ))}
                  </div>
                )}
                <div className={cn("mt-1.5 text-[10px]", t.role === "user" ? "text-white/60" : "text-slate-600")}>
                  {fmtTime(t.time)}
                </div>
              </div>
            </div>
          ))}
          {streaming && (
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <Spinner /> 助手正在调用工具查询…
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={submit} className="flex gap-2 border-t border-ink-700/70 p-4">
          <input className="input flex-1" placeholder="输入问题，Enter 发送…" value={input}
            onChange={(e) => setInput(e.target.value)} aria-label="提问" />
          <button type="submit" className="btn-primary" disabled={!input.trim() || streaming}>
            {streaming ? <Spinner /> : "发送"}
          </button>
        </form>
      </Card>

      <Card className="h-[calc(100vh-8rem)] overflow-y-auto">
        <h3 className="mb-3 text-sm font-medium text-slate-300">历史会话</h3>
        {!conversations || conversations.length === 0 ? (
          <p className="text-xs text-slate-600">暂无会话记录</p>
        ) : (
          <div className="space-y-1.5">
            {conversations.map((c) => (
              <button key={c.id}
                className={cn("w-full rounded-lg border px-3 py-2 text-left text-xs transition",
                  c.id === conversationId ? "border-sky-500/50 bg-sky-500/10 text-sky-200" : "border-ink-700 text-slate-400 hover:border-slate-500")}
                onClick={() => loadConversation(c.id)}>
                <div className="truncate">{c.title}</div>
                <div className="mt-0.5 text-[10px] text-slate-600">{fmtTime(c.created_at)}</div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
