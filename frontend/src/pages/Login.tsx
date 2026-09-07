import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/stores/auth";
import { errMsg, useUi } from "@/stores/ui";
import { Spinner } from "@/components/ui";

export default function Login() {
  const { login } = useAuth();
  const { toast } = useUi();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@aisoc.dev");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      toast("success", "欢迎回来");
      navigate("/");
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-sky-400 to-violet-500 text-xl font-extrabold text-white shadow-xl shadow-violet-500/20">AI</div>
          <div className="text-center">
            <h1 className="text-xl font-bold text-white">AISOC 控制台</h1>
            <p className="mt-1 text-xs text-slate-500">AI 驱动的安全运营中心 · 开源自托管</p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="card p-6">
          <label className="label" htmlFor="email">邮箱</label>
          <input id="email" type="email" required autoComplete="username" className="input mb-4"
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <label className="label" htmlFor="password">密码</label>
          <input id="password" type="password" required autoComplete="current-password" className="input mb-4"
            value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          {error && <div role="alert" className="mb-4 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? <Spinner /> : "登 录"}
          </button>
        </form>
        <p className="mt-4 text-center text-[11px] text-slate-600">
          初始管理员由部署种子创建 · 登录与全部操作均被审计
        </p>
      </div>
    </div>
  );
}
