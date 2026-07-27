import { avatarApi, personaApi, voiceApi } from "@oral/api-client";
import { useIp } from "@oral/stores";
import type { Persona } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import AssetNav from "../components/AssetNav";

const emptyForm = {
  name: "",
  domain: "知识科普",
  tone: "专业、接地气",
  values: "",
  tabooWords: "",
  audience: "",
  contentPillars: "",
  styleSamples: "",
  catchphrase: "",
  videoDuration: 60,
  ctaStyle: "",
  avoidTopics: "",
};

/** IP 档案（F-701 简化版：人设表单 + 资产绑定展示 + 激活切换） */
export default function PersonasPage() {
  const queryClient = useQueryClient();
  const { current, switch: switchIp, load } = useIp();
  const [editing, setEditing] = useState<Persona | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const { data: personas } = useQuery({
    queryKey: ["personas"],
    queryFn: () => personaApi.list(),
  });
  const { data: voices } = useQuery({
    queryKey: ["voices"],
    queryFn: () => voiceApi.list(),
  });
  const { data: avatars } = useQuery({
    queryKey: ["avatars"],
    queryFn: () => avatarApi.list(),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["personas"] });
    await load();
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        domain: form.domain,
        tone: form.tone,
        values: form.values,
        tabooWords: form.tabooWords.split(/[,，\s]+/).filter(Boolean),
        audience: form.audience,
        contentPillars: form.contentPillars.split(/[,，\s]+/).filter(Boolean),
        styleSamples: form.styleSamples,
        catchphrase: form.catchphrase,
        videoDuration: form.videoDuration,
        ctaStyle: form.ctaStyle,
        avoidTopics: form.avoidTopics.split(/[,，\s]+/).filter(Boolean),
      };
      if (editing) await personaApi.update(editing.id, payload);
      else await personaApi.create(payload);
      setEditing(null);
      setCreating(false);
      setForm(emptyForm);
      await refresh();
    } finally {
      setSaving(false);
    }
  };

  const bindAsset = async (
    p: Persona,
    field: "voiceId" | "avatarId",
    value: string,
  ) => {
    await personaApi.update(p.id, { [field]: value || null });
    await refresh();
  };

  const openEdit = (p: Persona) => {
    setEditing(p);
    setCreating(false);
    setForm({
      name: p.name,
      domain: p.domain,
      tone: p.tone,
      values: p.values,
      tabooWords: p.tabooWords.join(", "),
      audience: p.audience || "",
      contentPillars: (p.contentPillars || []).join(", "),
      styleSamples: p.styleSamples || "",
      catchphrase: p.catchphrase || "",
      videoDuration: p.videoDuration || 60,
      ctaStyle: p.ctaStyle || "",
      avoidTopics: (p.avoidTopics || []).join(", "),
    });
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">IP 档案</h1>
          <p className="mt-1 text-sm text-text-3">
            人设（领域/口吻/禁忌词）注入生成链路，多 IP 一键切换
          </p>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            setCreating(true);
            setEditing(null);
            setForm(emptyForm);
          }}
        >
          + 新建 IP
        </button>
      </div>

      <AssetNav />

      {/* 编辑/创建表单 */}
      {(creating || editing) && (
        <div className="glass-strong space-y-4 p-5">
          <h2 className="font-medium">
            {editing ? `编辑「${editing.name}」` : "新建 IP"}
          </h2>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">IP 名称</label>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="如：财税老周"
              />
            </div>
            <div>
              <label className="label">领域</label>
              <input
                className="input"
                value={form.domain}
                onChange={(e) => setForm({ ...form, domain: e.target.value })}
                placeholder="如：财税科普"
              />
            </div>
            <div>
              <label className="label">口吻风格</label>
              <input
                className="input"
                value={form.tone}
                onChange={(e) => setForm({ ...form, tone: e.target.value })}
                placeholder="如：犀利、接地气、有梗"
              />
            </div>
            <div>
              <label className="label">目标受众</label>
              <input
                className="input"
                value={form.audience}
                onChange={(e) => setForm({ ...form, audience: e.target.value })}
                placeholder="如：30-45岁个体户老板"
              />
            </div>
            <div>
              <label className="label">内容支柱（逗号分隔）</label>
              <input
                className="input"
                value={form.contentPillars}
                onChange={(e) =>
                  setForm({ ...form, contentPillars: e.target.value })
                }
                placeholder="如：税务筹划, 工商注册, 政策速报"
              />
            </div>
            <div>
              <label className="label">口头禅 / 标志性开场白</label>
              <input
                className="input"
                value={form.catchphrase}
                onChange={(e) =>
                  setForm({ ...form, catchphrase: e.target.value })
                }
                placeholder="如：大家好，我是老周，今天咱们聊聊…"
              />
            </div>
            <div>
              <label className="label">偏好视频时长（秒）</label>
              <input
                className="input"
                type="number"
                value={form.videoDuration}
                onChange={(e) =>
                  setForm({
                    ...form,
                    videoDuration: Number(e.target.value) || 60,
                  })
                }
                placeholder="60"
              />
            </div>
            <div>
              <label className="label">行动号召风格（CTA）</label>
              <input
                className="input"
                value={form.ctaStyle}
                onChange={(e) => setForm({ ...form, ctaStyle: e.target.value })}
                placeholder="如：关注收藏 / 评论区扒1 / 私信领取"
              />
            </div>
            <div>
              <label className="label">禁忌词（逗号分隔）</label>
              <input
                className="input"
                value={form.tabooWords}
                onChange={(e) =>
                  setForm({ ...form, tabooWords: e.target.value })
                }
                placeholder="如：最, 第一, 保证"
              />
            </div>
            <div>
              <label className="label">回避话题（逗号分隔）</label>
              <input
                className="input"
                value={form.avoidTopics}
                onChange={(e) =>
                  setForm({ ...form, avoidTopics: e.target.value })
                }
                placeholder="如：竞品名, 政治敏感"
              />
            </div>
            <div className="md:col-span-2">
              <label className="label">价值观 / 人设背景</label>
              <textarea
                className="input min-h-20"
                value={form.values}
                onChange={(e) => setForm({ ...form, values: e.target.value })}
                placeholder="一句话说清这个 IP 是谁、为谁说话"
              />
            </div>
            <div className="md:col-span-2">
              <label className="label">
                风格样本（粘贴 2-3 段代表性文案，AI 会模仿这个语气）
              </label>
              <textarea
                className="input min-h-28"
                value={form.styleSamples}
                onChange={(e) =>
                  setForm({ ...form, styleSamples: e.target.value })
                }
                placeholder="粘贴你以前的爆款文案片段…"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              className="btn-ghost"
              onClick={() => {
                setCreating(false);
                setEditing(null);
              }}
            >
              取消
            </button>
            <button
              className="btn-primary"
              disabled={saving || !form.name.trim()}
              onClick={save}
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      )}

      {/* IP 卡片网格 */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(personas ?? []).map((p) => (
          <div
            key={p.id}
            className={`glass card-hover p-4 ${p.isActive ? "border-brand-from/50" : ""}`}
          >
            <div className="flex items-center gap-3">
              <span
                className="flex h-11 w-11 items-center justify-center rounded-2xl text-lg font-bold text-white"
                style={{ background: p.avatarGrad }}
              >
                {p.avatarChar}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-bold">{p.name}</span>
                  {p.isActive && (
                    <span className="chip border-success/40 text-[10px] text-success">
                      当前
                    </span>
                  )}
                </div>
                <div className="text-xs text-text-3">{p.domain}</div>
              </div>
              {!p.isActive && (
                <button
                  className="btn-ghost px-2.5 py-1 text-xs"
                  onClick={() => void switchIp(p.id)}
                >
                  切换
                </button>
              )}
            </div>

            <div className="mt-3 space-y-1.5 text-xs text-text-3">
              <div>口吻：{p.tone || "—"}</div>
              {p.tabooWords.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {p.tabooWords.map((w) => (
                    <span
                      key={w}
                      className="chip border-danger/30 text-[10px] text-danger/80"
                    >
                      禁:{w}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 资产绑定 */}
            <div className="mt-3 space-y-2 border-t border-stroke pt-3">
              <div className="flex items-center gap-2 text-xs">
                <span className="w-14 shrink-0 text-text-3">声音</span>
                <select
                  className="input h-10 flex-1 px-3 py-0 text-sm"
                  value={p.voiceId ?? ""}
                  onChange={(e) => void bindAsset(p, "voiceId", e.target.value)}
                >
                  <option value="">未绑定</option>
                  {(voices ?? []).map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="w-14 shrink-0 text-text-3">数字人</span>
                <select
                  className="input h-10 flex-1 px-3 py-0 text-sm"
                  value={p.avatarId ?? ""}
                  onChange={(e) =>
                    void bindAsset(p, "avatarId", e.target.value)
                  }
                >
                  <option value="">未绑定</option>
                  {(avatars ?? []).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button
              className="btn-ghost mt-3 w-full text-xs"
              onClick={() => openEdit(p)}
            >
              编辑人设
            </button>
          </div>
        ))}
      </div>

      {(personas ?? []).length === 0 && (
        <div className="glass py-16 text-center text-text-3">
          还没有 IP 档案，点击右上角「新建 IP」开始
        </div>
      )}
    </div>
  );
}
