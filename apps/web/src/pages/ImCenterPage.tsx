import {
  imApi,
  publishApi,
  type IMConversation,
  type IMMessage,
} from "@oral/api-client";
import type { PublishAccount } from "@oral/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, EyeOff, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import PlatformIcon from "../components/PlatformIcon";
import { isDesktopShell, openDouyinIM } from "../lib/douyinWebview";

/** 私信中心：账号筛选 + 会话列表 + 对话气泡 */
export default function ImCenterPage() {
  const queryClient = useQueryClient();
  const [activeConv, setActiveConv] = useState<IMConversation | null>(null);
  const [sendError, setSendError] = useState("");
  const [filterAccountId, setFilterAccountId] = useState<string>("");
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [conversationPage, setConversationPage] = useState(1);
  const [messagePage, setMessagePage] = useState(1);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: accounts } = useQuery({
    queryKey: ["publish-accounts"],
    queryFn: () => publishApi.accounts(),
    refetchInterval: 60_000,
  });

  const { data: convData } = useQuery({
    queryKey: [
      "im-conversations",
      conversationPage,
      searchTerm,
      filterAccountId,
    ],
    queryFn: () =>
      imApi.conversations(conversationPage, 30, searchTerm, filterAccountId),
    refetchInterval: 10_000,
  });

  const { data: msgData } = useQuery({
    queryKey: ["im-messages", activeConv?.id, messagePage, searchTerm],
    queryFn: () => imApi.messages(activeConv!.id, messagePage, 50, searchTerm),
    enabled: !!activeConv,
    refetchInterval: 5_000,
  });

  const accountList: PublishAccount[] = accounts ?? [];
  const accountMap = useMemo(() => {
    const m = new Map<string, PublishAccount>();
    accountList.forEach((a) => m.set(a.id, a));
    return m;
  }, [accountList]);

  const conversations = convData?.items ?? [];

  const messages = (msgData?.items ?? []).slice().reverse();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const selectConv = (conv: IMConversation) => {
    setActiveConv(conv);
    setMessagePage(1);
    if (conv.unreadCount > 0) {
      void imApi
        .markRead(conv.id)
        .then(() =>
          queryClient.invalidateQueries({ queryKey: ["im-conversations"] }),
        );
    }
  };

  const handleManualReply = async () => {
    if (!activeConv) return;
    setSendError("");
    try {
      await openDouyinIM(activeConv.accountId);
    } catch {
      setSendError("抖音官方页面打开失败，请稍后重试。");
    }
  };

  const parseContent = (content: string): string => {
    try {
      const obj = JSON.parse(content);
      return obj.text ?? content;
    } catch {
      return content;
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">私信中心</h1>
          <p className="mt-1 text-sm text-text-3">
            聚合抖音私信 · 当前为“监听 + 人工网页版回复”模式（方案 E）
          </p>
        </div>
        <button
          type="button"
          disabled={isDesktopShell() && !activeConv}
          onClick={() => {
            if (activeConv) {
              void openDouyinIM(activeConv.accountId);
            } else if (!isDesktopShell()) {
              void openDouyinIM();
            }
          }}
          className="shrink-0 rounded-lg bg-brand-from px-3.5 py-2 text-xs font-medium text-white transition hover:opacity-90"
        >
          {isDesktopShell()
            ? activeConv
              ? "在抖音回复（新窗口）"
              : "选择会话后回复"
            : "打开抖音"}
        </button>
      </div>

      <div className="flex gap-4" style={{ height: "calc(100vh - 220px)" }}>
        {/* 会话列表 */}
        <div className="glass flex w-72 shrink-0 flex-col overflow-hidden">
          {/* 账号筛选器 */}
          <div className="space-y-2 border-b border-stroke px-3 py-2">
            <form
              onSubmit={(event) => {
                event.preventDefault();
                setSearchTerm(searchInput.trim());
                setConversationPage(1);
                setMessagePage(1);
                setActiveConv(null);
              }}
            >
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="搜索昵称、UID 或消息"
                maxLength={100}
                className="w-full rounded-lg border border-stroke bg-white/5 px-2.5 py-1.5 text-xs outline-none focus:border-brand-from/50"
              />
            </form>
            <select
              value={filterAccountId}
              onChange={(e) => {
                setFilterAccountId(e.target.value);
                setConversationPage(1);
                setActiveConv(null);
              }}
              className="w-full rounded-lg border border-stroke bg-white/5 px-2.5 py-1.5 text-xs outline-none focus:border-brand-from/50"
            >
              <option value="">全部账号</option>
              {accountList
                .filter((a) => a.platform === "douyin")
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nickname}
                  </option>
                ))}
            </select>
          </div>
          <div className="border-b border-stroke px-4 py-2.5 text-sm font-medium">
            会话（{convData?.total ?? 0}）
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {conversations.map((conv) => (
              <button
                key={conv.id}
                onClick={() => selectConv(conv)}
                className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-white/5 ${
                  activeConv?.id === conv.id
                    ? "bg-brand-from/10 border-l-2 border-brand-from"
                    : ""
                }`}
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-sm">
                  {conv.remoteNickname?.[0] ?? "?"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {conv.remoteNickname || "未知用户"}
                  </span>
                  <span className="block truncate text-xs text-text-3">
                    {accountMap.get(conv.accountId)?.nickname && (
                      <span className="mr-1 text-brand-from/70">
                        @{accountMap.get(conv.accountId)!.nickname}
                      </span>
                    )}
                    {new Date(conv.lastMessageAt).toLocaleString("zh-CN", {
                      month: "numeric",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </span>
                {conv.unreadCount > 0 && (
                  <span className="rounded-full bg-danger/20 px-1.5 py-px text-[10px] font-bold text-danger">
                    {conv.unreadCount > 99 ? "99+" : conv.unreadCount}
                  </span>
                )}
              </button>
            ))}
            {conversations.length === 0 && (
              <div className="py-12 text-center text-sm text-text-3">
                暂无私信会话
              </div>
            )}
          </div>
          <div className="flex items-center justify-between border-t border-stroke px-3 py-2 text-xs text-text-3">
            <button
              className="btn-ghost px-2 py-1"
              disabled={conversationPage <= 1}
              onClick={() => {
                setConversationPage((page) => Math.max(1, page - 1));
                setActiveConv(null);
              }}
            >
              上一页
            </button>
            <span>第 {conversationPage} 页</span>
            <button
              className="btn-ghost px-2 py-1"
              disabled={(convData?.total ?? 0) <= conversationPage * 30}
              onClick={() => {
                setConversationPage((page) => page + 1);
                setActiveConv(null);
              }}
            >
              下一页
            </button>
          </div>
        </div>

        {/* 对话区 */}
        <div className="glass flex min-w-0 flex-1 flex-col overflow-hidden">
          {activeConv ? (
            <>
              <div className="flex items-center gap-2 border-b border-stroke px-4 py-3">
                <PlatformIcon platform="douyin" size={16} />
                <span className="text-sm font-medium">
                  {activeConv.remoteNickname || "未知用户"}
                </span>
                <span className="text-xs text-text-3">
                  UID: {activeConv.remoteUid}
                </span>
                {accountMap.get(activeConv.accountId) && (
                  <span className="ml-auto chip text-[10px]">
                    <PlatformIcon platform="douyin" size={12} />
                    {accountMap.get(activeConv.accountId)!.nickname}
                  </span>
                )}
              </div>
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
                {(msgData?.total ?? 0) > 50 && (
                  <div className="flex items-center justify-center gap-3 text-xs text-text-3">
                    <button
                      className="btn-ghost px-2 py-1"
                      disabled={messagePage <= 1}
                      onClick={() =>
                        setMessagePage((page) => Math.max(1, page - 1))
                      }
                    >
                      较新一页
                    </button>
                    <span>第 {messagePage} 页</span>
                    <button
                      className="btn-ghost px-2 py-1"
                      disabled={(msgData?.total ?? 0) <= messagePage * 50}
                      onClick={() => setMessagePage((page) => page + 1)}
                    >
                      更早一页
                    </button>
                  </div>
                )}
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    msg={msg}
                    parseContent={parseContent}
                    onManualReply={handleManualReply}
                  />
                ))}
                <div ref={bottomRef} />
              </div>
              {sendError && (
                <div className="border-t border-danger/20 bg-danger/10 px-4 py-2 text-xs text-danger">
                  {sendError}
                </div>
              )}
              <div className="border-t border-stroke bg-black/20 px-4 py-3 text-xs text-text-3 flex items-center gap-2">
                <EyeOff className="h-3.5 w-3.5" />
                仅监听与 WebView
                辅助，发送动作已改为官方页面手动执行。可点击左侧消息“建议回复”快速打开抖音。
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-text-3">
              选择左侧会话查看私信
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  msg,
  parseContent,
  onManualReply,
}: {
  msg: IMMessage;
  parseContent: (c: string) => string;
  onManualReply: () => Promise<void>;
}) {
  const isOut = msg.direction === "out";
  const text = parseContent(msg.content);
  return (
    <div className={`flex ${isOut ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[70%] rounded-2xl px-3.5 py-2 text-sm ${
          isOut ? "bg-brand-from/20 text-text-1" : "bg-white/5 text-text-1"
        }`}
      >
        <p className="whitespace-pre-wrap break-words">{text}</p>
        <div className="mt-1 flex items-center gap-2 text-[10px] text-text-3">
          <span>
            {new Date(msg.createdAt).toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          {msg.autoReplied && (
            <span className="inline-flex items-center gap-0.5 text-brand-to">
              <Zap className="h-2.5 w-2.5" /> 规则建议
            </span>
          )}
          {isOut && msg.sendStatus === "pending" && <span>发送中</span>}
          {isOut && msg.sendStatus === "sent" && <span>已发送</span>}
          {isOut && msg.sendStatus === "failed" && (
            <span className="text-danger">发送失败 · {msg.sendError}</span>
          )}
          {isOut && msg.sendStatus === "manual" && (
            <span className="text-warning">已转人工</span>
          )}
          {isOut && msg.sendStatus === "suggested" && (
            <span className="text-brand-to">建议回复 · 未发送</span>
          )}
          {isOut && msg.sendStatus === "blocked" && (
            <span className="text-danger">
              已拦截 · {msg.moderationReason || "内容审核未通过"}
            </span>
          )}
          {isOut && msg.sendStatus === "canceled" && (
            <span className="text-warning">已由安全开关取消</span>
          )}
        </div>
        {isOut && msg.sendStatus === "failed" && (
          <div className="mt-2 flex justify-end gap-2 text-[11px]">
            <button
              className="rounded border border-stroke px-2 py-1 hover:bg-white/5"
              onClick={() => void onManualReply()}
            >
              <BellRing className="mr-1 inline h-3 w-3" /> 打开抖音回复
            </button>
          </div>
        )}
        {isOut && msg.sendStatus === "suggested" && (
          <div className="mt-2 flex justify-end text-[11px]">
            <button
              className="rounded border border-stroke px-2 py-1 hover:bg-white/5"
              onClick={() => void onManualReply()}
            >
              打开抖音，人工确认并发送
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
