import { authApi, HttpError, setTokens } from "@oral/api-client";
import { useSession } from "@oral/stores";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** 登录/注册（F-601：JWT 双令牌 + 设备绑定） */
export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useSession((s) => s.login);
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "register") {
        const tokens = await authApi.register(phone, password, nickname || phone.slice(-4));
        setTokens(tokens);
        // 注册后直接补登录态
        await login(phone, password);
      } else {
        await login(phone, password);
      }
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof HttpError ? err.body.message : "网络异常，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-grad text-2xl font-black text-white shadow-cta">
            口
          </div>
          <h1 className="text-2xl font-bold">
            口播<span className="text-grad">IP智能体</span>
          </h1>
          <p className="mt-2 text-sm text-text-3">爆款复刻 · 声音克隆 · 数字人 · 全平台发布</p>
        </div>

        <form onSubmit={submit} className="glass-strong space-y-4 p-6">
          <div className="mb-2 grid grid-cols-2 gap-1 rounded-xl bg-white/5 p-1">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`rounded-lg py-1.5 text-sm transition-colors ${
                  mode === m ? "bg-brand-grad text-white" : "text-text-3 hover:text-text-1"
                }`}
              >
                {m === "login" ? "登录" : "注册"}
              </button>
            ))}
          </div>

          <div>
            <label className="label">手机号</label>
            <input
              className="input"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="请输入手机号"
              required
            />
          </div>
          {mode === "register" && (
            <div>
              <label className="label">昵称</label>
              <input
                className="input"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder="你的 IP 称呼（可后改）"
              />
            </div>
          )}
          <div>
            <label className="label">密码</label>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 位"
              minLength={6}
              required
            />
          </div>

          {error && (
            <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}

          <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
            {loading ? "请稍候…" : mode === "login" ? "登录" : "注册并进入"}
          </button>

          <p className="text-center text-xs text-text-3">
            新用户注册即赠 <span className="text-grad font-bold">12,430</span> 算力点数
          </p>
        </form>
      </div>
    </div>
  );
}
