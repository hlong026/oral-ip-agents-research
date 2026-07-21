import { activationApi, authApi, HttpError, setTokens } from "@oral/api-client";
import { useSession } from "@oral/stores";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

/** 激活码注册页（替代原注册流程） */
export default function ActivatePage() {
  const [step, setStep] = useState<1 | 2>(1);
  const [code, setCode] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [codeInfo, setCodeInfo] = useState<{ planType: string; quotaAmount: number; durationDays: number; message: string } | null>(null);
  const navigate = useNavigate();

  const validateCode = async () => {
    setError("");
    setLoading(true);
    try {
      const info = await activationApi.validateCode(code);
      if (!info.valid) {
        setError(info.message || "激活码无效");
        return;
      }
      setCodeInfo(info);
      setStep(2);
    } catch (err) {
      setError(err instanceof HttpError ? err.body.message : "网络异常，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const result = await activationApi.activate(code, phone, password, nickname || phone.slice(-4));
      setTokens({ accessToken: result.accessToken, refreshToken: result.refreshToken, expiresIn: result.expiresIn });
      // 直接用返回的 token 获取用户信息
      const user = await authApi.me();
      useSession.setState({ user, ready: true });
      navigate("/", { replace: true });
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
          <p className="mt-2 text-sm text-text-3">激活码注册 · 开启 AI 创作之旅</p>
        </div>

        <div className="glass-strong space-y-4 p-6">
          {step === 1 ? (
            <>
              <div>
                <label className="label">激活码</label>
                <input
                  className="input font-mono tracking-wider"
                  value={code}
                  onChange={(e) => setCode(e.target.value.toUpperCase())}
                  placeholder="ORAL-XXXX-XXXX-XXXX-XXXX"
                  required
                />
                <p className="mt-1 text-xs text-text-3">请输入您获得的激活码</p>
              </div>

              {error && (
                <div className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
                  {error}
                </div>
              )}

              <button onClick={validateCode} disabled={loading || !code.trim()} className="btn-primary w-full py-2.5">
                {loading ? "验证中…" : "验证激活码"}
              </button>

              <p className="text-center text-xs text-text-3">
                已有账号？{" "}
                <button onClick={() => navigate("/login")} className="text-grad font-medium hover:underline">
                  直接登录
                </button>
              </p>
            </>
          ) : (
            <form onSubmit={submit}>
              {/* 码信息展示 */}
              {codeInfo && (
                <div className="mb-4 rounded-xl border border-brand-from/30 bg-brand-from/5 px-4 py-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-text-1">{codeInfo.message}</span>
                    <span className="rounded-full bg-brand-grad px-2 py-0.5 text-xs text-white">
                      {codeInfo.durationDays > 0 ? `${codeInfo.durationDays}天` : "永久"}
                    </span>
                  </div>
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="label">手机号</label>
                  <input
                    className="input"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="请输入手机号（作为登录账号）"
                    required
                  />
                </div>
                <div>
                  <label className="label">昵称</label>
                  <input
                    className="input"
                    value={nickname}
                    onChange={(e) => setNickname(e.target.value)}
                    placeholder="你的 IP 称呼（可后改）"
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

                <button type="submit" disabled={loading} className="btn-primary w-full py-2.5">
                  {loading ? "激活中…" : "激活并进入"}
                </button>

                <button
                  type="button"
                  onClick={() => { setStep(1); setCodeInfo(null); setError(""); }}
                  className="w-full text-center text-xs text-text-3 hover:text-text-1"
                >
                  ← 返回重新输入激活码
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
