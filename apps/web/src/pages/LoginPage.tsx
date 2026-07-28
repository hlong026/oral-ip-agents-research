import { HttpError, activationApi } from "@oral/api-client";
import type { CodeInfo } from "@oral/api-client";
import { useSession } from "@oral/stores";
import { useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

/** 套餐类型编码 → 用户可读名称 */
const PLAN_TYPE_LABELS: Record<string, string> = {
  trial: "试用体验",
  weekly_bundle: "周会员",
  monthly_bundle: "月度会员",
  quarterly_bundle: "季度会员",
  annual_bundle: "年度会员",
  internal_annual: "内部年度",
  points_pack: "积分加油包",
};

/** 登录页（激活码即账号：首次登录自动开户并绑定本设备） */
export default function LoginPage() {
  const [code, setCode] = useState("");
  const [codeInfo, setCodeInfo] = useState<CodeInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useSession((s) => s.login);
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const planExpired = searchParams.get("reason") === "plan_expired";
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  // 失焦预校验：展示码对应的套餐信息（未使用码才返回 valid）
  const precheck = async () => {
    const value = code.trim();
    if (!value) {
      setCodeInfo(null);
      return;
    }
    try {
      setCodeInfo(await activationApi.validateCode(value));
    } catch {
      setCodeInfo(null);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(code.trim());
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof HttpError) {
        const messages: Record<string, string> = {
          DEVICE_MISMATCH:
            "该激活码已绑定其他设备，请在原设备使用或联系管理员解绑",
          CODE_UNAVAILABLE: "激活码无效或已作废，请核对后重试",
          CODE_EXPIRED: "激活码已过期，请更换新的激活码",
          RATE_LIMITED: "尝试过于频繁，请稍后再试",
        };
        setError(messages[err.body.code] ?? err.body.message);
      } else {
        setError("网络异常，请稍后再试");
      }
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
          {planExpired && (
            <div className="rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
              套餐已到期：登录后可在「套餐与充值」页兑换新激活码续期
            </div>
          )}
          <div>
            <label className="label">激活码</label>
            <input
              className="input font-mono tracking-wide"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onBlur={() => void precheck()}
              placeholder="XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"
              autoComplete="off"
              spellCheck={false}
              required
            />
            <p className="mt-1.5 text-xs text-text-3">
              首次登录将自动开通账号并绑定本设备
            </p>
          </div>

          {codeInfo?.valid && (
            <div className="rounded-xl border border-success/30 bg-success/10 px-3 py-2 text-xs text-success">
              新激活码可用：{PLAN_TYPE_LABELS[codeInfo.planType] ?? codeInfo.planType}
              套餐 · {codeInfo.durationDays}{" "}
              天 · {codeInfo.quotaAmount.toLocaleString()} 点算力
            </div>
          )}

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
            {loading ? "请稍候…" : "登录 / 激活"}
          </button>

          <p className="text-center text-xs text-text-3">
            激活码即账号，请妥善保管，切勿外泄
          </p>
        </form>
      </div>
    </div>
  );
}
