import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ApiKey, AuditLog, User } from "@/api/types";
import { Badge, Card, EmptyState, Modal, Skeleton, Spinner } from "@/components/ui";
import { fmtTime } from "@/lib/utils";
import { errMsg, useUi } from "@/stores/ui";
import { useAuth } from "@/stores/auth";

export default function Admin() {
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">平台管理</h1>
        <p className="text-xs text-slate-500">用户与角色 · API Key · 审计日志</p>
      </div>
      <UsersSection />
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
        <ApiKeysSection />
        <AuditSection />
      </div>
    </div>
  );
}

function UsersSection() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const { toast } = useUi();
  const { data: users, isLoading } = useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/api/v1/auth/users") });
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState<string[]>(["analyst"]);

  const create = useMutation({
    mutationFn: () => api.post("/api/v1/auth/users", { email, password, display_name: name, roles }),
    onSuccess: () => {
      toast("success", "用户已创建");
      setOpen(false); setEmail(""); setPassword(""); setName("");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/api/v1/auth/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => toast("error", errMsg(e)),
  });

  return (
    <Card className="!p-0">
      <div className="flex items-center justify-between px-5 py-4">
        <h3 className="text-sm font-medium text-slate-300">用户管理（{users?.length ?? 0}）</h3>
        <button className="btn-ghost !py-1.5 text-xs" onClick={() => setOpen(true)}>+ 新用户</button>
      </div>
      {isLoading ? (
        <div className="space-y-2 p-4">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
      ) : (
        <div className="divide-y divide-ink-700/50">
          {(users ?? []).map((u) => (
            <div key={u.id} className="flex items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm text-slate-200">{u.display_name}
                  {u.id === me?.id && <span className="ml-2 text-[10px] text-sky-400">（当前登录）</span>}
                </div>
                <div className="font-mono text-[11px] text-slate-500">{u.email}</div>
              </div>
              <Badge className="border-violet-500/30 bg-violet-500/10 text-violet-300">{u.roles.join("/")}</Badge>
              {u.id !== me?.id && (
                <button className="text-xs text-slate-500 hover:text-amber-300"
                  onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                  {u.is_active ? "停用" : "启用"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="创建用户">
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <div><label className="label" htmlFor="ue">邮箱</label><input id="ue" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
          <div><label className="label" htmlFor="un">显示名</label><input id="un" required className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><label className="label" htmlFor="up">初始密码（≥10 位）</label><input id="up" type="password" required minLength={10} className="input" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          <div>
            <span className="label">角色</span>
            <div className="flex gap-2">
              {["admin", "analyst", "viewer"].map((r) => (
                <button type="button" key={r}
                  className={`rounded-lg border px-3 py-1.5 text-xs ${roles.includes(r) ? "border-sky-500 bg-sky-500/15 text-sky-200" : "border-ink-600 text-slate-400"}`}
                  onClick={() => setRoles((rs) => rs.includes(r) ? rs.filter((x) => x !== r) : [...rs, r])}>
                  {r}
                </button>
              ))}
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>取消</button>
            <button type="submit" className="btn-primary" disabled={create.isPending}>{create.isPending ? <Spinner /> : "创建"}</button>
          </div>
        </form>
      </Modal>
    </Card>
  );
}

function ApiKeysSection() {
  const qc = useQueryClient();
  const { toast } = useUi();
  const { data: keys, isLoading } = useQuery({ queryKey: ["apikeys"], queryFn: () => api.get<ApiKey[]>("/api/v1/auth/api-keys") });
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.post<ApiKey & { plaintext_key: string }>("/api/v1/auth/api-keys", { name, scopes: ["alerts:write"] }),
    onSuccess: (k) => {
      setCreated(k.plaintext_key);
      setName("");
      qc.invalidateQueries({ queryKey: ["apikeys"] });
    },
    onError: (e) => toast("error", errMsg(e)),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/auth/api-keys/${id}`),
    onSuccess: () => { toast("success", "已吊销"); qc.invalidateQueries({ queryKey: ["apikeys"] }); },
    onError: (e) => toast("error", errMsg(e)),
  });

  return (
    <Card className="!p-0">
      <div className="flex items-center justify-between px-5 py-4">
        <h3 className="text-sm font-medium text-slate-300">API Key（告警接入）</h3>
        <button className="btn-ghost !py-1.5 text-xs" onClick={() => { setCreated(null); setOpen(true); }}>+ 新 Key</button>
      </div>
      {isLoading ? (
        <div className="p-4"><Skeleton className="h-20" /></div>
      ) : !keys || keys.length === 0 ? (
        <EmptyState title="尚无 API Key" hint="创建后用于告警源接入（X-API-Key）" icon="🔑" />
      ) : (
        <div className="divide-y divide-ink-700/50">
          {keys.map((k) => (
            <div key={k.id} className="flex items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm text-slate-200">{k.name}</div>
                <div className="font-mono text-[11px] text-slate-500">{k.key_prefix}… · {k.scopes.join(",")} · {k.rate_limit_per_min}/min</div>
              </div>
              <Badge className={k.is_active ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : "border-slate-600 text-slate-500"}>
                {k.is_active ? "active" : "revoked"}
              </Badge>
              {k.is_active && (
                <button className="text-xs text-slate-500 hover:text-red-300"
                  onClick={() => window.confirm(`吊销 Key「${k.name}」？接入方将立即 401。`) && revoke.mutate(k.id)}>吊销</button>
              )}
            </div>
          ))}
        </div>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="创建 API Key">
        {created ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
              请立即保存，此明文仅显示一次：
            </div>
            <code className="block break-all rounded-lg bg-ink-950 p-3 font-mono text-xs text-emerald-300">{created}</code>
            <button className="btn-primary w-full" onClick={() => { navigator.clipboard.writeText(created); toast("success", "已复制"); }}>复制并关闭</button>
          </div>
        ) : (
          <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
            <div><label className="label" htmlFor="kn">用途名称</label><input id="kn" required className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="如 waf-ingest" /></div>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>取消</button>
              <button type="submit" className="btn-primary" disabled={!name.trim() || create.isPending}>{create.isPending ? <Spinner /> : "创建"}</button>
            </div>
          </form>
        )}
      </Modal>
    </Card>
  );
}

function AuditSection() {
  const { data, isLoading } = useQuery({ queryKey: ["audit"], queryFn: () => api.get<AuditLog[]>("/api/v1/audit") });
  return (
    <Card className="!p-0">
      <h3 className="px-5 py-4 text-sm font-medium text-slate-300">审计日志（最近）</h3>
      {isLoading ? (
        <div className="space-y-2 p-4">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-8" />)}</div>
      ) : !data || data.length === 0 ? (
        <EmptyState title="暂无审计记录" icon="🧾" />
      ) : (
        <div className="max-h-80 overflow-y-auto divide-y divide-ink-700/50">
          {data.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-5 py-2.5 text-xs">
              <span className="font-mono text-slate-500">{fmtTime(a.created_at)}</span>
              <Badge className="border-ink-600 text-slate-300">{a.action}</Badge>
              <span className="truncate text-slate-500">{a.resource_type}{a.resource_id ? ` · ${a.resource_id.slice(0, 8)}` : ""}</span>
              <span className="ml-auto shrink-0 font-mono text-[10px] text-slate-600">{a.actor_type}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
