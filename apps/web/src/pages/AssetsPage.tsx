import AssetNav from "../components/AssetNav";

const FILTERS = [
  { key: "all", label: "全部", count: 110 },
  { key: "cover", label: "封面", count: 36 },
  { key: "bgm", label: "BGM", count: 12 },
  { key: "clip", label: "视频片段", count: 58 },
  { key: "watermark", label: "水印", count: 4 },
] as const;

const MATERIALS = [
  { icon: "封面", name: "节税系列封面 · 红底", tags: ["封面", "常用"] },
  { icon: "♪", name: "轻快商务 BGM", tags: ["BGM", "0:58"] },
  { icon: "▶", name: "开场钩子片段包（8 条）", tags: ["视频片段"] },
  { icon: "✦", name: "李老师角标水印", tags: ["水印", "默认启用"] },
  { icon: "封面", name: "新公司法封面 · 蓝底", tags: ["封面"] },
  { icon: "♪", name: "悬念感 BGM", tags: ["BGM", "0:41"] },
  { icon: "▶", name: "办公室空镜 B-roll", tags: ["视频片段", "4 条"] },
] as const;

/** 素材库（F-702 为 P1 能力，MVP 仅静态壳，V1.1 上线真实能力） */
export default function AssetsPage() {
  return (
    <div className="space-y-5">
      <AssetNav />

      <div className="flex items-center justify-between rounded-card border border-info/30 bg-info/10 px-4 py-3 text-sm text-info">
        <span>ℹ 素材库为 V1.1 能力，当前为效果预览；上传与智能混剪将在素材库版本开放</span>
        <span className="chip border-info/40 text-info">V1.1 上线</span>
      </div>

      {/* 上传 + 筛选 + 用量 */}
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" disabled title="V1.1 开放">
          ⬆ 上传素材
        </button>
        {FILTERS.map((f, i) => (
          <span key={f.key} className={`chip px-3 py-1 ${i === 0 ? "border-brand-from/50 bg-brand-from/15 text-text-1" : ""}`}>
            {f.label} {f.count}
          </span>
        ))}
        <div className="ml-auto flex items-center gap-2 text-xs text-text-3">
          已用 2.1 GB / 10 GB
          <div className="h-1.5 w-28 overflow-hidden rounded-full bg-white/5">
            <div className="h-full rounded-full bg-brand-grad-x" style={{ width: "21%" }} />
          </div>
        </div>
      </div>

      {/* 素材网格 */}
      <div>
        <div className="mb-3 flex items-baseline gap-3">
          <h2 className="font-medium">最近使用</h2>
          <span className="text-xs text-text-3">按使用时间排序</span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {MATERIALS.map((m) => (
            <div key={m.name} className="glass card-hover p-3">
              <div className="flex h-28 items-center justify-center rounded-lg bg-white/5 text-sm text-text-3">{m.icon}</div>
              <div className="mt-2.5 text-sm font-medium">{m.name}</div>
              <div className="mt-1.5 flex gap-1.5">
                {m.tags.map((t) => (
                  <span key={t} className="chip text-[11px]">
                    {t}
                  </span>
                ))}
              </div>
            </div>
          ))}
          <div className="glass flex min-h-48 items-center justify-center border-dashed p-3 text-text-3">＋ 上传新素材</div>
        </div>
      </div>

      <div className="rounded-card border border-info/30 bg-info/10 px-4 py-3 text-sm text-info">
        ℹ 上传的素材仅用于您自己的视频合成；BGM 区提供平台曲库授权曲目，商用无忧。合成时可在「模板中心」为每个 IP 设定默认素材组合。
      </div>
    </div>
  );
}
