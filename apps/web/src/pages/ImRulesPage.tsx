import {
  imApi,
  type IMAutoReplyRule,
  type IMListenerStatus,
} from "@oral/api-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

/** 建议回复规则配置 + 监听状态面板 */
export default function ImRulesPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editRule, setEditRule] = useState<IMAutoReplyRule | null>(null);

  const { data: rules } = useQuery({
    queryKey: ["im-rules"],
    queryFn: () => imApi.rules(),
  });
  const { data: listeners } = useQuery({
    queryKey: ["im-listeners"],
    queryFn: () => imApi.listenerStatus(),
    refetchInterval: 15_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["im-rules"] });
    void queryClient.invalidateQueries({ queryKey: ["im-listeners"] });
  };

  const toggle = async (rule: IMAutoReplyRule) => {
    await imApi.toggleRule(rule.id);
    invalidate();
  };

  const remove = async (rule: IMAutoReplyRule) => {
    await imApi.deleteRule(rule.id);
    invalidate();
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">建议回复规则</h1>
          <p className="mt-1 text-sm text-text-3">
            匹配私信并生成待人工确认的回复建议，不由服务端发送
          </p>
        </div>
        <button
          className="btn-primary px-4 py-2 text-sm"
          onClick={() => {
            setEditRule(null);
            setShowForm(true);
          }}
        >
          + 新建规则
        </button>
      </div>

      {/* 监听状态 */}
      <ListenerPanel listeners={listeners ?? []} onChange={invalidate} />

      {/* 规则列表 */}
      <div className="glass p-5">
        <h2 className="mb-3 font-medium">规则列表（{rules?.length ?? 0}）</h2>
        <div className="space-y-2">
          {(rules ?? []).map((rule) => (
            <div
              key={rule.id}
              className="flex items-center gap-3 rounded-xl border border-stroke/50 px-4 py-3"
            >
              <span
                className={`h-2 w-2 rounded-full ${rule.enabled ? "bg-success" : "bg-text-3"}`}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{rule.name}</span>
                  <span className="chip text-[10px]">
                    {triggerLabel(rule.triggerType)}
                  </span>
                  <span className="chip text-[10px]">
                    {rule.replyMode === "llm" ? "AI 生成" : "模板"}
                  </span>
                  <span className="chip text-[10px]">仅建议</span>
                </div>
                <div className="mt-0.5 text-xs text-text-3">
                  {rule.triggerType === "keyword" &&
                    `匹配: ${rule.triggerPattern}`}
                  {rule.triggerType !== "keyword" && "匹配所有私信"}
                  {" · "}延迟 {rule.delayMin}~{rule.delayMax}s · 日上限{" "}
                  {rule.dailyLimit}
                </div>
              </div>
              <div className="flex gap-1.5">
                <button
                  className="btn-ghost px-2.5 py-1 text-xs"
                  onClick={() => {
                    setEditRule(rule);
                    setShowForm(true);
                  }}
                >
                  编辑
                </button>
                <button
                  className="btn-ghost px-2.5 py-1 text-xs"
                  onClick={() => void toggle(rule)}
                >
                  {rule.enabled ? "禁用" : "启用"}
                </button>
                <button
                  className="btn-ghost px-2.5 py-1 text-xs text-danger"
                  onClick={() => void remove(rule)}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
          {(rules ?? []).length === 0 && (
            <div className="py-10 text-center text-sm text-text-3">
              暂无规则，点击右上角新建
            </div>
          )}
        </div>
      </div>

      {showForm && (
        <RuleForm
          rule={editRule}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false);
            invalidate();
          }}
        />
      )}
    </div>
  );
}

function triggerLabel(t: string) {
  return t === "keyword" ? "关键词" : t === "llm" ? "LLM" : "全量";
}

/** 监听状态面板 */
function ListenerPanel({
  listeners,
  onChange,
}: {
  listeners: IMListenerStatus[];
  onChange: () => void;
}) {
  const start = async (accountId: string) => {
    await imApi.startListener(accountId);
    onChange();
  };
  const stop = async (accountId: string) => {
    await imApi.stopListener(accountId);
    onChange();
  };

  return (
    <div className="glass p-5">
      <h2 className="mb-3 font-medium">消息监听状态</h2>
      {listeners.length === 0 ? (
        <p className="text-sm text-text-3">
          暂无监听中的账号，请在账号管理中绑定抖音账号后启动监听
        </p>
      ) : (
        <div className="space-y-2">
          {listeners.map((l) => (
            <div
              key={l.accountId}
              className="flex items-center gap-3 rounded-xl border border-stroke/50 px-4 py-3"
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  l.status === "listening"
                    ? "bg-success animate-pulse"
                    : l.status === "error"
                      ? "bg-danger"
                      : "bg-text-3"
                }`}
              />
              <div className="min-w-0 flex-1">
                <span className="text-sm font-medium">
                  {l.accountNickname || l.accountId.slice(0, 8)}
                </span>
                <span className="ml-2 text-xs text-text-3">
                  {l.status === "listening"
                    ? "监听中"
                    : l.status === "error"
                      ? `错误: ${l.errorMsg}`
                      : "已停止"}
                </span>
              </div>
              {l.status === "listening" ? (
                <button
                  className="btn-ghost px-3 py-1 text-xs"
                  onClick={() => void stop(l.accountId)}
                >
                  停止
                </button>
              ) : (
                <button
                  className="btn-primary px-3 py-1 text-xs"
                  onClick={() => void start(l.accountId)}
                >
                  启动监听
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 规则编辑表单（弹层） */
function RuleForm({
  rule,
  onClose,
  onSaved,
}: {
  rule: IMAutoReplyRule | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(rule?.name ?? "");
  const [triggerType, setTriggerType] = useState(rule?.triggerType ?? "all");
  const [triggerPattern, setTriggerPattern] = useState(
    rule?.triggerPattern ?? "",
  );
  const [replyMode, setReplyMode] = useState(rule?.replyMode ?? "template");
  const [replyTemplate, setReplyTemplate] = useState(rule?.replyTemplate ?? "");
  const [llmPrompt, setLlmPrompt] = useState(rule?.llmPrompt ?? "");
  const [dailyLimit, setDailyLimit] = useState(rule?.dailyLimit ?? 50);
  const [delayMin, setDelayMin] = useState(rule?.delayMin ?? 3);
  const [delayMax, setDelayMax] = useState(rule?.delayMax ?? 30);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const data = {
        name,
        triggerType,
        triggerPattern,
        replyMode,
        deliveryMode: "suggestion" as const,
        replyTemplate,
        llmPrompt,
        dailyLimit,
        delayMin,
        delayMax,
      };
      if (rule) {
        await imApi.updateRule(rule.id, data);
      } else {
        await imApi.createRule(data);
      }
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="glass-strong w-[480px] max-h-[80vh] overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-4 text-base font-bold">
          {rule ? "编辑规则" : "新建规则"}
        </h3>
        <div className="space-y-3">
          <Field label="规则名称">
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：价格咨询建议"
            />
          </Field>
          <Field label="触发方式">
            <select
              className="input"
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value)}
            >
              <option value="all">全量（所有私信）</option>
              <option value="keyword">关键词匹配</option>
              <option value="llm">LLM 智能（所有私信）</option>
            </select>
          </Field>
          {triggerType === "keyword" && (
            <Field label="关键词/正则">
              <input
                className="input"
                value={triggerPattern}
                onChange={(e) => setTriggerPattern(e.target.value)}
                placeholder="如：价格|多少钱|怎么买"
              />
            </Field>
          )}
          <Field label="回复模式">
            <select
              className="input"
              value={replyMode}
              onChange={(e) => setReplyMode(e.target.value)}
            >
              <option value="template">固定模板</option>
              <option value="llm">AI 生成（LLM）</option>
            </select>
          </Field>
          <Field label="交付方式">
            <p className="rounded-lg border border-stroke bg-white/5 px-3 py-2 text-sm text-text-2">
              仅生成建议，由用户在抖音官方页面人工发送
            </p>
          </Field>
          {replyMode === "template" && (
            <Field label="回复模板">
              <textarea
                className="input min-h-[80px]"
                value={replyTemplate}
                onChange={(e) => setReplyTemplate(e.target.value)}
                placeholder="您好，感谢关注！…"
              />
            </Field>
          )}
          {replyMode === "llm" && (
            <Field label="LLM Prompt（补充人设）">
              <textarea
                className="input min-h-[80px]"
                value={llmPrompt}
                onChange={(e) => setLlmPrompt(e.target.value)}
                placeholder="你是一个友好的客服，语气亲切…"
              />
            </Field>
          )}
          <div className="grid grid-cols-3 gap-3">
            <Field label="日上限">
              <input
                type="number"
                min={1}
                className="input"
                value={dailyLimit}
                onChange={(e) =>
                  setDailyLimit(Math.max(1, +e.target.value || 1))
                }
              />
            </Field>
            <Field label="最小延迟(s)">
              <input
                type="number"
                min={0}
                className="input"
                value={delayMin}
                onChange={(e) => setDelayMin(Math.max(0, +e.target.value || 0))}
              />
            </Field>
            <Field label="最大延迟(s)">
              <input
                type="number"
                min={0}
                className="input"
                value={delayMax}
                onChange={(e) => setDelayMax(Math.max(0, +e.target.value || 0))}
              />
            </Field>
          </div>
          {delayMax < delayMin && (
            <p className="mt-1 text-xs text-red-400">
              最大延迟不能小于最小延迟
            </p>
          )}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-ghost px-4 py-2 text-sm" onClick={onClose}>
            取消
          </button>
          <button
            className="btn-primary px-4 py-2 text-sm"
            disabled={saving || !name.trim()}
            onClick={() => void save()}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-text-3">{label}</span>
      {children}
    </label>
  );
}
