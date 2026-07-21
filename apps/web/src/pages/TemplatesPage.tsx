import { useIp } from "@oral/stores";
import AssetNav from "../components/AssetNav";

const TEMPLATES = [
  {
    name: "知识口播 A",
    preview: "大字幕 · 红封面",
    desc: "适合政策解读、干货科普",
    using: true,
  },
  {
    name: "避坑指南 B",
    preview: "黄黑警示风",
    desc: "适合避坑、风险提示类选题",
    using: false,
  },
  {
    name: "对话访谈 C",
    preview: "访谈双字幕",
    desc: "适合双人问答、连麦切片",
    using: false,
  },
  {
    name: "带货种草 D",
    preview: "商品挂车版式",
    desc: "含价格贴片与挂车锚点位",
    using: false,
  },
  {
    name: "系列课程 E",
    preview: "课程章节版式",
    desc: "含章节编号与进度条",
    using: false,
  },
] as const;

const COMPOSE_PARTS = [
  { name: "字幕样式", desc: "字体/字号/描边/位置/关键词高亮" },
  { name: "封面版式", desc: "底图/标题排版/IP 角标" },
  { name: "声音组合", desc: "默认 BGM 与音量避让策略" },
  { name: "发布预设", desc: "默认话题标签与@账号" },
] as const;

/** 模板中心（F-724 为 P1 能力，MVP 仅静态壳，V1.1 上线真实能力） */
export default function TemplatesPage() {
  const { current } = useIp();

  return (
    <div className="space-y-5">
      <AssetNav />

      <div className="flex items-center justify-between rounded-card border border-info/30 bg-info/10 px-4 py-3 text-sm text-info">
        <span>
          ℹ 模板中心为 V1.1
          能力，当前为效果预览；合成参数模板化与从成片反建模板将随后开放
        </span>
        <span className="chip border-info/40 text-info">V1.1 上线</span>
      </div>

      {/* 首屏：当前 IP 正在使用的模板 */}
      <div className="glass flex flex-wrap items-center gap-5 p-5">
        <div className="flex h-32 w-20 shrink-0 items-center justify-center rounded-lg bg-white/5 text-center text-xs text-text-3">
          模板
          <br />
          预览
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-bold">知识口播 A</span>
            <span className="chip border-brand-from/50 text-brand-to">
              {current?.name ?? "当前 IP"} · 默认
            </span>
          </div>
          <div className="mt-1.5 text-sm text-text-3">
            白底描边大字幕（底部安全区）· 红底标题封面 · 轻快商务 BGM · IP
            角标水印
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <span className="chip text-[11px]">字幕：粗体 44px</span>
            <span className="chip text-[11px]">封面：红底大字</span>
            <span className="chip text-[11px]">BGM：-18dB 避让</span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <button
            className="btn-primary px-3 py-1 text-xs"
            disabled
            title="V1.1 开放"
          >
            ✎ 编辑模板
          </button>
          <button
            className="btn-ghost px-3 py-1 text-xs"
            disabled
            title="V1.1 开放"
          >
            应用于全部 IP
          </button>
        </div>
      </div>

      {/* 模板库 */}
      <div>
        <div className="mb-3 flex items-baseline gap-3">
          <h2 className="font-medium">模板库（{TEMPLATES.length}）</h2>
          <span className="text-xs text-text-3">
            点击卡片即可预览并设为默认
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {TEMPLATES.map((t) => (
            <div
              key={t.name}
              className={`glass card-hover p-4 ${t.using ? "border-brand-to/50" : ""}`}
            >
              <div className="flex h-32 items-center justify-center rounded-lg bg-white/5 text-sm text-text-3">
                {t.preview}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <b>{t.name}</b>
                {t.using ? (
                  <span className="chip ml-auto border-brand-from/50 text-[11px] text-brand-to">
                    使用中
                  </span>
                ) : (
                  <button
                    className="btn-ghost ml-auto px-2.5 py-0.5 text-xs"
                    disabled
                    title="V1.1 开放"
                  >
                    设为默认
                  </button>
                )}
              </div>
              <div className="mt-1.5 text-xs text-text-3">{t.desc}</div>
            </div>
          ))}
          <div className="glass flex min-h-48 flex-col items-center justify-center gap-2 border-dashed p-4 text-text-3">
            <div className="text-2xl">＋</div>从成片反建模板
          </div>
        </div>
      </div>

      {/* 模板组成说明 */}
      <div className="glass p-5 opacity-90">
        <h2 className="mb-3 font-medium">模板由什么组成</h2>
        <div className="grid gap-3 md:grid-cols-4">
          {COMPOSE_PARTS.map((p) => (
            <div key={p.name}>
              <div className="text-sm font-medium">{p.name}</div>
              <div className="mt-1 text-xs text-text-3">{p.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
