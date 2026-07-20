import { settingsApi } from "@oral/api-client";
import { webBridge } from "@oral/platform/web";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

/** 系统设置：算力策略 + 视频解析&ASR配置 + 会话策略 + 关于 */
export default function SettingsPage() {
  const { data: compute } = useQuery({
    queryKey: ["compute-status"],
    queryFn: () => webBridge.getComputeStatus(),
  });

  // 视频解析 & ASR 配置（从后端加载，保存到后端 DB）
  const [douyidouAppId, setDouyidouAppId] = useState("");
  const [douyidouAppSecret, setDouyidouAppSecret] = useState("");
  const [douyidouBaseUrl, setDouyidouBaseUrl] = useState("https://gateway.diadi.cn");
  const [dashscopeApiKey, setDashscopeApiKey] = useState("");
  const [dashscopeWorkspaceId, setDashscopeWorkspaceId] = useState("");
  const [dashscopeRegion, setDashscopeRegion] = useState("cn-beijing");
  const [asrModel, setAsrModel] = useState("fun-asr");
  const [asrFlashModel, setAsrFlashModel] = useState("fun-asr-flash-2026-06-15");
  const [asrFlashThreshold, setAsrFlashThreshold] = useState("300");
  // LLM 配置
  const [deepseekApiKey, setDeepseekApiKey] = useState("");
  const [deepseekBaseUrl, setDeepseekBaseUrl] = useState("https://api.deepseek.com/v1");
  const [deepseekModel, setDeepseekModel] = useState("deepseek-chat");
  // 声音/数字人配置
  const [feiyingApiKey, setFeiyingApiKey] = useState("");
  const [feiyingBaseUrl, setFeiyingBaseUrl] = useState("https://hfw-api.hifly.cc");
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 加载后端配置
  useEffect(() => {
    settingsApi.get().then((res) => {
      const s = res.settings;
      if (s.douyidou_app_id) setDouyidouAppId(s.douyidou_app_id);
      if (s.douyidou_app_secret) setDouyidouAppSecret(s.douyidou_app_secret);
      if (s.douyidou_base_url) setDouyidouBaseUrl(s.douyidou_base_url);
      if (s.dashscope_api_key) setDashscopeApiKey(s.dashscope_api_key);
      if (s.dashscope_workspace_id) setDashscopeWorkspaceId(s.dashscope_workspace_id);
      if (s.dashscope_region) setDashscopeRegion(s.dashscope_region);
      if (s.asr_model) setAsrModel(s.asr_model);
      if (s.asr_flash_model) setAsrFlashModel(s.asr_flash_model);
      if (s.asr_flash_threshold_sec) setAsrFlashThreshold(s.asr_flash_threshold_sec);
      if (s.deepseek_api_key) setDeepseekApiKey(s.deepseek_api_key);
      if (s.deepseek_base_url) setDeepseekBaseUrl(s.deepseek_base_url);
      if (s.deepseek_model) setDeepseekModel(s.deepseek_model);
      if (s.feiying_api_key) setFeiyingApiKey(s.feiying_api_key);
      if (s.feiying_base_url) setFeiyingBaseUrl(s.feiying_base_url);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setError("");
    try {
      await settingsApi.save({
        douyidou_app_id: douyidouAppId,
        douyidou_app_secret: douyidouAppSecret,
        douyidou_base_url: douyidouBaseUrl,
        dashscope_api_key: dashscopeApiKey,
        dashscope_workspace_id: dashscopeWorkspaceId,
        dashscope_region: dashscopeRegion,
        asr_model: asrModel,
        asr_flash_model: asrFlashModel,
        asr_flash_threshold_sec: asrFlashThreshold,
        deepseek_api_key: deepseekApiKey,
        deepseek_base_url: deepseekBaseUrl,
        deepseek_model: deepseekModel,
        feiying_api_key: feiyingApiKey,
        feiying_base_url: feiyingBaseUrl,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.response?.data?.detail?.message || e?.message || "保存失败，请重试");
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <h1 className="text-xl font-bold">系统设置</h1>

      {/* 视频解析 & ASR 配置 */}
      <div className="glass p-5">
        <h2 className="mb-1 font-medium">视频解析 & 语音转写</h2>
        <p className="mb-4 text-xs text-text-3">配置第三方视频解析和阿里云ASR语音转写服务，实现链接→文案自动提取</p>

        {/* Douyidou 视频解析 */}
        <div className="mb-5 rounded-xl border border-stroke bg-white/[0.02] p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-medium">🎬 Douyidou 视频解析</span>
            <a
              href="https://www.douyidou.cc"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-brand-to hover:underline"
            >
              获取 API Key
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-text-3">App ID</label>
              <input
                className="input h-10 text-sm"
                placeholder="输入 Douyidou App ID"
                value={douyidouAppId}
                onChange={(e) => setDouyidouAppId(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-3">App Secret</label>
              <input
                className="input h-10 text-sm"
                type="password"
                placeholder="输入 Douyidou App Secret"
                value={douyidouAppSecret}
                onChange={(e) => setDouyidouAppSecret(e.target.value)}
              />
            </div>
          </div>
          <div className="mt-3">
            <label className="mb-1 block text-xs text-text-3">网关地址</label>
            <input
              className="input h-10 text-sm"
              placeholder="https://gateway.diadi.cn"
              value={douyidouBaseUrl}
              onChange={(e) => setDouyidouBaseUrl(e.target.value)}
            />
          </div>
          <p className="mt-2 text-xs text-text-3">支持抖音、小红书、快手、B站等多平台视频链接/ID解析</p>
        </div>

        {/* 阿里云 Fun-ASR */}
        <div className="rounded-xl border border-stroke bg-white/[0.02] p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-medium">🎙️ 阿里云 Fun-ASR 语音转写</span>
            <a
              href="https://bailian.console.aliyun.com/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-brand-to hover:underline"
            >
              申请 API Key
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-text-3">DashScope API Key</label>
              <input
                className="input h-10 text-sm"
                type="password"
                placeholder="sk-xxxxxxxxxxxxxxxx"
                value={dashscopeApiKey}
                onChange={(e) => setDashscopeApiKey(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-3">Workspace ID（选填，企业专属）</label>
              <input
                className="input h-10 text-sm"
                placeholder="普通用户无需填写"
                value={dashscopeWorkspaceId}
                onChange={(e) => setDashscopeWorkspaceId(e.target.value)}
              />
            </div>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-text-3">服务区域</label>
              <select
                className="input h-10 text-sm"
                value={dashscopeRegion}
                onChange={(e) => setDashscopeRegion(e.target.value)}
              >
                <option value="cn-beijing">华北2（北京）</option>
                <option value="ap-southeast-1">新加坡</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-3">ASR 模型</label>
              <select
                className="input h-10 text-sm"
                value={asrModel}
                onChange={(e) => setAsrModel(e.target.value)}
              >
                <option value="fun-asr">Fun-ASR（异步，≤12h/2GB）</option>
                <option value="fun-asr-flash">Fun-ASR-Flash（同步，≤5min）</option>
              </select>
            </div>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-text-3">Flash 同步模型</label>
              <input
                className="input h-10 text-sm"
                placeholder="fun-asr-flash-2026-06-15"
                value={asrFlashModel}
                onChange={(e) => setAsrFlashModel(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-text-3">分流阈值（秒，≤此值走Flash）</label>
              <input
                className="input h-10 text-sm"
                type="number"
                placeholder="300"
                value={asrFlashThreshold}
                onChange={(e) => setAsrFlashThreshold(e.target.value)}
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-text-3">
            智能分流：≤5分钟短视频走Flash同步（秒级返回），&gt;5分钟走异步轮询。支持 mp4/mov/mp3/wav 等16种格式
          </p>
        </div>

        <button onClick={handleSave} disabled={loading} className="btn-primary mt-4 w-full">
          {saved ? "✓ 已保存" : loading ? "加载中…" : "保存配置"}
        </button>
        {error && <p className="mt-2 text-center text-xs text-red-400">{error}</p>}
      </div>

      {/* LLM 配置 */}
      <div className="glass p-5">
        <h2 className="mb-1 font-medium">🧠 LLM 文案仿写（DeepSeek）</h2>
        <p className="mb-4 text-xs text-text-3">配置 DeepSeek 大模型，用于文案仿写、选题生成、结构拆解等智能功能</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-text-3">API Key</label>
            <input
              className="input h-10 text-sm"
              type="password"
              placeholder="sk-xxxxxxxxxxxxxxxx"
              value={deepseekApiKey}
              onChange={(e) => setDeepseekApiKey(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-3">模型</label>
            <input
              className="input h-10 text-sm"
              placeholder="deepseek-chat"
              value={deepseekModel}
              onChange={(e) => setDeepseekModel(e.target.value)}
            />
          </div>
        </div>
        <div className="mt-3">
          <label className="mb-1 block text-xs text-text-3">Base URL</label>
          <input
            className="input h-10 text-sm"
            placeholder="https://api.deepseek.com/v1"
            value={deepseekBaseUrl}
            onChange={(e) => setDeepseekBaseUrl(e.target.value)}
          />
        </div>
      </div>

      {/* 声音/数字人配置 */}
      <div className="glass p-5">
        <h2 className="mb-1 font-medium">🎭 声音克隆 & 数字人</h2>
        <p className="mb-4 text-xs text-text-3">配置声音克隆与数字人形象服务，用于 TTS 合成和视频创作</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-text-3">API Key</label>
            <input
              className="input h-10 text-sm"
              type="password"
              placeholder="输入 API Key"
              value={feiyingApiKey}
              onChange={(e) => setFeiyingApiKey(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-3">Base URL</label>
            <input
              className="input h-10 text-sm"
              placeholder="https://hfw-api.hifly.cc"
              value={feiyingBaseUrl}
              onChange={(e) => setFeiyingBaseUrl(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* 算力策略 */}
      <div className="glass p-5">
        <h2 className="mb-1 font-medium">算力策略</h2>
        <p className="mb-4 text-xs text-text-3">纯云端优先（CLOUD_FIRST）；本地引擎为 V1.1+ 可选下载组件</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-brand-from/40 bg-brand-from/10 p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">云端通道</span>
              <span className="chip border-success/40 text-success">当前生效</span>
            </div>
            <p className="mt-2 text-xs text-text-3">所有算力经云端 Worker 执行，失败按降级链自动切换供应商</p>
          </div>
          <div className="rounded-xl border border-stroke bg-white/[0.02] p-4 opacity-70">
            <div className="flex items-center justify-between">
              <span className="font-medium">本地引擎</span>
              <span className="chip">V1.1 开放</span>
            </div>
            <p className="mt-2 text-xs text-text-3">
              {compute?.localAvailable ? "已就绪" : "未安装 · 安装后 Whisper/合成可在本地免扣点执行"}
            </p>
            <button className="btn-ghost mt-3 w-full text-xs" disabled>
              下载本地引擎（即将开放）
            </button>
          </div>
        </div>
      </div>

      {/* 会话策略 */}
      <div className="glass p-5">
        <h2 className="mb-4 font-medium">会话与安全</h2>
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between">
            <div>
              <div>单端登录互踢</div>
              <div className="text-xs text-text-3">开启后新设备登录将踢出旧设备（服务端配置）</div>
            </div>
            <span className="chip">默认关闭</span>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <div>设备绑定</div>
              <div className="text-xs text-text-3">登录令牌与设备指纹绑定（F-601）</div>
            </div>
            <span className="chip border-success/40 text-success">已启用</span>
          </div>
        </div>
      </div>

      {/* 合规 */}
      <div className="glass p-5">
        <h2 className="mb-4 font-medium">合规声明</h2>
        <ul className="list-inside space-y-1.5 text-xs text-text-3">
          <li>· 声音克隆与形象克隆必须本人授权（consent_token 强制校验）</li>
          <li>· 复刻内容经过去重改写，请确保拥有原内容合理使用权利</li>
          <li>· 发布行为由所授权平台账号承担，请遵守各平台社区规范</li>
        </ul>
      </div>

      <div className="text-center text-xs text-text-3">口播IP智能体 V1.0 · CLOUD_FIRST</div>
    </div>
  );
}
