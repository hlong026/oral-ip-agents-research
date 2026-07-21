import {
  imApi,
  publishApi,
  type IMConversation,
  type IMMessage,
} from "@oral/api-client";
import type { PublishAccount } from "@oral/types";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import PlatformIcon from "../components/PlatformIcon";

/** 私信中心：账号筛选 + 会话列表 + 对话气泡 */
export default function ImCenterPage() {
  const [activeConv, setActiveConv] = useState<IMConversation | null>(null);
  const [filterAccountId, setFilterAccountId] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: accounts } = useQuery({
    queryKey: ["publish-accounts"],
    queryFn: () => publishApi.accounts(),
    refetchInterval: 60_000,
  });

  const { data: convData } = useQuery({
    queryKey: ["im-conversations"],
    queryFn: () => imApi.conversations(1, 50),
    refetchInterval: 10_000,
  });

  const { data: msgData } = useQuery({
    queryKey: ["im-messages", activeConv?.id],
    queryFn: () => imApi.messages(activeConv!.id, 1, 100),
    enabled: !!activeConv,
    refetchInterval: 5_000,
  });

  const accountList: PublishAccount[] = accounts ?? [];
  const accountMap = useMemo(() => {
    const m = new Map<string, PublishAccount>();
    accountList.forEach((a) => m.set(a.id, a));
    return m;
  }, [accountList]);

  const conversations = useMemo(() => {
    const items = convData?.items ?? [];
    if (!filterAccountId) return items;
    return items.filter((c) => c.accountId === filterAccountId);
  }, [convData, filterAccountId]);

  const messages = (msgData?.items ?? []).slice().reverse();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const selectConv = (conv: IMConversation) => {
    setActiveConv(conv);
    if (conv.unreadCount > 0) void imApi.markRead(conv.id);
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
      <div>
        <h1 className="text-xl font-bold">私信中心</h1>
        <p className="mt-1 text-sm text-text-3">
          实时接收绑定账号的新抖音私信 · 当前不包含历史会话同步
        </p>
      </div>

      <div className="flex gap-4" style={{ height: "calc(100vh - 220px)" }}>
        {/* 会话列表 */}
        <div className="glass flex w-72 shrink-0 flex-col overflow-hidden">
          {/* 账号筛选器 */}
          <div className="border-b border-stroke px-3 py-2">
            <select
              value={filterAccountId}
              onChange={(e) => {
                setFilterAccountId(e.target.value);
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
            会话（{conversations.length}）
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
                  {conversationName(conv)[0]}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {conversationName(conv)}
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
              <div className="px-5 py-12 text-center text-sm text-text-3">
                启动监听后，新收到的真实私信会显示在这里
              </div>
            )}
          </div>
        </div>

        {/* 对话区 */}
        <div className="glass flex min-w-0 flex-1 flex-col overflow-hidden">
          {activeConv ? (
            <>
              <div className="flex items-center gap-2 border-b border-stroke px-4 py-3">
                <PlatformIcon platform="douyin" size={16} />
                <span className="text-sm font-medium">
                  {conversationName(activeConv)}
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
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    msg={msg}
                    parseContent={parseContent}
                  />
                ))}
                <div ref={bottomRef} />
              </div>
              <div className="border-t border-stroke px-4 py-3 text-xs text-text-3">
                当前仅开放真实私信接收；发送与自动回复需完成抖音 web_protect
                签名接入后再启用。
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

function conversationName(conv: IMConversation): string {
  return conv.remoteNickname || `抖音用户 ${conv.remoteUid.slice(-6)}`;
}

function MessageBubble({
  msg,
  parseContent,
}: {
  msg: IMMessage;
  parseContent: (c: string) => string;
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
            <span className="text-brand-to">⚡ 自动回复</span>
          )}
        </div>
      </div>
    </div>
  );
}
