import { FormEvent, useState } from "react";
import { useNavigate } from "react-router";
import { adminApi } from "@oral/admin-api-client";

export default function LoginPage() {
  const navigate = useNavigate();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await adminApi.login(phone, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center px-4">
      <form
        className="glass-strong w-full max-w-md space-y-5 p-6"
        onSubmit={submit}
      >
        <div>
          <p className="text-sm text-brand-to">管理后台</p>
          <h1 className="mt-2 text-2xl font-semibold">管理员登录</h1>
          <p className="mt-2 text-sm text-text-3">
            管理套餐 SKU、积分价格、激活码和供应商配置。
          </p>
        </div>
        <div>
          <label className="label" htmlFor="phone">
            手机号
          </label>
          <input
            id="phone"
            className="input"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="password">
            密码
          </label>
          <input
            id="password"
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && (
          <p className="rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        <button
          className="btn-primary w-full"
          disabled={submitting || !phone || !password}
        >
          {submitting ? "登录中..." : "登录管理端"}
        </button>
      </form>
    </div>
  );
}
