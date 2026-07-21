import { HttpError } from "@oral/api-client";
import { useSession } from "@oral/stores";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** 登录页（激活码注册入口） */
export default function LoginPage() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
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
      await login(phone, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(
        err instanceof HttpError ? err.body.message : "网络异常，请稍后再试",
      );
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
          <p className="mt-2 text-sm text-text-3">
            爆款复刻 · 声音克隆 · 数字人 · 全平台发布
          </p>
        </div>

        <form onSubmit={submit} className="glass-strong space-y-4 p-6">
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

          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full py-2.5"
          >
            {loading ? "请稍候…" : "登录"}
          </button>

          <p className="text-center text-xs text-text-3">
            还没有账号？{" "}
            <button
              type="button"
              onClick={() => navigate("/activate")}
              className="text-grad font-medium hover:underline"
            >
              激活码注册
            </button>
          </p>
        </form>
      </div>
    </div>
  );
}
