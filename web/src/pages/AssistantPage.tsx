/**
 * AssistantPage — Full-page AI assistant for event creation.
 *
 * Features:
 * - Markdown rendering in agent responses
 * - Shift+Enter for multiline input
 * - Tool call status indicators
 * - HITL interactive choice buttons
 * - File upload (images, Excel, PDF)
 */
import { useState, useRef, useEffect, useCallback, DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Send, Paperclip, FileImage, FileSpreadsheet, FileText,
  Loader2, Bot, Trash2, ExternalLink, X, Sparkles, Upload,
} from 'lucide-react';
import { apiClient } from '../lib/api';
import { ChatMessage, parseChoices } from '../components/ChatMessage';
import type { ChatMessageData, ToolCallInfo, QuickReplyData } from '../components/ChatMessage';

interface SubTask {
  id: string;
  plugin: string;
  description: string;
  status: string;
}

const WELCOME_MSG = '你好！我是 Eventron 智能排座助手。\n\n'
  + '我可以帮你：\n'
  + '- **上传邀请函/海报** → 自动提取活动信息并创建\n'
  + '- **上传 Excel 名单** → 自动导入参会者\n'
  + '- **描述需求** → 自动创建活动 + 布局 + 铭牌 + 签到\n'
  + '- **多步骤任务** → 自动规划、逐步执行\n\n'
  + '试试说「帮我创建一个100人的圆桌年会」或上传一张活动海报开始吧！';

export function AssistantPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // ── Persist chat state in sessionStorage ─────────────────
  const STORAGE_KEY = 'eventron_assistant_chat';

  const loadPersistedState = () => {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const saved = JSON.parse(raw);
      return {
        messages: (saved.messages || []).map((m: ChatMessageData) => ({
          ...m,
          timestamp: m.timestamp ? new Date(m.timestamp) : undefined,
        })),
        sessionId: saved.sessionId || null,
        taskPlan: saved.taskPlan || null,
        lastEventId: saved.lastEventId || null,
      };
    } catch {
      return null;
    }
  };

  const persisted = loadPersistedState();
  const [messages, setMessages] = useState<ChatMessageData[]>(
    persisted?.messages?.length
      ? persisted.messages
      : [{ role: 'assistant', content: WELCOME_MSG, timestamp: new Date() }],
  );
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(persisted?.sessionId ?? null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [taskPlan, setTaskPlan] = useState<SubTask[] | null>(persisted?.taskPlan ?? null);
  const [lastEventId, setLastEventId] = useState<string | null>(persisted?.lastEventId ?? null);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);

  const ACCEPTED_TYPES = ['image/', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel', 'text/csv', 'application/pdf'];
  const isAcceptedFile = (file: File) =>
    ACCEPTED_TYPES.some((t) => file.type.startsWith(t)) || /\.(xlsx?|csv|pdf)$/i.test(file.name);

  const handleDragEnter = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer?.types.includes('Files')) setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    dragCounterRef.current = 0;
    const files = Array.from(e.dataTransfer?.files || []).filter(isAcceptedFile);
    if (files.length > 0) {
      setPendingFiles((prev) => [...prev, ...files]);
    }
  }, []);

  // Save to sessionStorage whenever state changes
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        messages,
        sessionId,
        taskPlan,
        lastEventId,
      }));
    } catch {
      // quota exceeded — silently ignore
    }
  }, [messages, sessionId, taskPlan, lastEventId]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => { scrollToBottom(); }, [messages]);
  useEffect(() => { textareaRef.current?.focus(); }, []);

  // Auto-resize textarea
  const adjustTextareaHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta || ta.offsetHeight === 0) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
  }, []);

  useEffect(() => { adjustTextareaHeight(); }, [input, adjustTextareaHeight]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const ro = new ResizeObserver(() => { adjustTextareaHeight(); });
    ro.observe(ta);
    return () => ro.disconnect();
  }, [adjustTextareaHeight]);

  const chatMutation = useMutation({
    mutationFn: ({ message, files }: { message: string; files: File[] }) =>
      apiClient.sendAgentChat(message, {
        eventId: lastEventId || undefined,
        sessionId: sessionId || undefined,
        files,
      }),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      const rawQr = (data.quick_replies || []) as QuickReplyData[];
      const choices = rawQr.length > 0 ? undefined : parseChoices(data.reply) || undefined;
      const newMsg: ChatMessageData = {
        role: 'assistant',
        content: data.reply,
        timestamp: new Date(),
        toolCalls: data.tool_calls as ToolCallInfo[] | undefined,
        quickReplies: rawQr.length > 0 ? rawQr : undefined,
        choices: choices && choices.length > 0 ? choices : undefined,
        parts: data.parts || undefined,
      };
      if (data.event_id) {
        newMsg.eventId = data.event_id;
        setLastEventId(data.event_id);
      }
      setMessages((prev) => [...prev, newMsg]);
      if (data.task_plan) setTaskPlan(data.task_plan);
      if (data.action_taken) {
        queryClient.invalidateQueries({ queryKey: ['events'] });
        queryClient.invalidateQueries({ queryKey: ['seats'] });
        queryClient.invalidateQueries({ queryKey: ['attendees'] });
        queryClient.invalidateQueries({ queryKey: ['badge-templates'] });
      }
    },
    onError: (err) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `**出错了：** ${err instanceof Error ? err.message : '请重试'}`,
          timestamp: new Date(),
        },
      ]);
    },
  });

  const doSend = useCallback((msg: string, files: File[] = []) => {
    if ((!msg.trim() && files.length === 0) || chatMutation.isPending) return;

    const attachments = files.map((f) => ({
      name: f.name,
      type: f.type.startsWith('image/') ? 'image' :
            f.name.match(/\.(xlsx?|csv)$/i) ? 'excel' :
            f.name.endsWith('.pdf') ? 'pdf' : 'file',
    }));

    setMessages((prev) => [
      ...prev,
      {
        role: 'user' as const,
        content: msg.trim() || `上传了 ${files.length} 个文件`,
        timestamp: new Date(),
        attachments: attachments.length > 0 ? attachments : undefined,
      },
    ]);
    setInput('');
    setPendingFiles([]);
    chatMutation.mutate({
      message: msg.trim() || '请分析这些文件',
      files,
    });
  }, [chatMutation]);

  const handleSend = () => {
    doSend(input, [...pendingFiles]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    // Shift+Enter: let default textarea behavior insert newline
  };

  const handleChoiceSelect = (choice: string) => {
    doSend(choice);
  };

  const handleClear = () => {
    setMessages([
      { role: 'assistant', content: '对话已清空。有什么我可以帮你的？', timestamp: new Date() },
    ]);
    setSessionId(null);
    setTaskPlan(null);
    setLastEventId(null);
    setPendingFiles([]);
    sessionStorage.removeItem(STORAGE_KEY);
  };

  const getFileIcon = (file: File) => {
    if (file.type.startsWith('image/')) return <FileImage size={14} />;
    if (file.name.match(/\.(xlsx?|csv)$/i)) return <FileSpreadsheet size={14} />;
    return <FileText size={14} />;
  };

  return (
    <div
      className="flex flex-col flex-1 min-h-0 relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-50 bg-indigo-50/80 border-2 border-dashed border-indigo-400 rounded-xl flex flex-col items-center justify-center pointer-events-none">
          <Upload size={40} className="text-indigo-500 mb-2" />
          <p className="text-indigo-600 font-medium text-sm">松开即可上传文件</p>
          <p className="text-indigo-400 text-xs mt-1">支持图片、Excel、PDF</p>
        </div>
      )}
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-gray-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-indigo-100 rounded-xl flex items-center justify-center">
            <Sparkles size={22} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900">AI 助手</h1>
            <p className="text-xs text-gray-500">上传海报/名单 · 对话式创建活动 · 多Agent协作</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {lastEventId && (
            <button
              onClick={() => navigate(`/events/${lastEventId}`)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
            >
              <ExternalLink size={14} />
              查看活动
            </button>
          )}
          <button
            onClick={handleClear}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
            title="清空对话"
          >
            <Trash2 size={14} />
            清空
          </button>
        </div>
      </div>

      {/* Task Plan Banner */}
      {taskPlan && taskPlan.length > 0 && (
        <div className="bg-indigo-50 border-b border-indigo-100 px-4 py-2.5 flex-shrink-0">
          <div className="text-xs font-semibold text-indigo-700 mb-1.5">任务计划</div>
          <div className="space-y-1">
            {taskPlan.map((task) => {
              const pluginLabel: Record<string, string> = {
                organizer: '🏢 创建活动',
                seating: '🪑 排座布局',
                badge: '🏷️ 铭牌设计',
                checkin: '✅ 签到设置',
                pagegen: '📱 页面生成',
              };
              return (
                <div key={task.id} className="flex items-center gap-2 text-sm">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    task.status === 'done' ? 'bg-green-500' :
                    task.status === 'in_progress' ? 'bg-yellow-500 animate-pulse' :
                    task.status === 'error' ? 'bg-red-500' : 'bg-gray-300'
                  }`} />
                  <span className="text-gray-700">
                    {pluginLabel[task.plugin] || task.description}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4 min-h-0">
        {messages.map((msg, idx) => (
          <ChatMessage
            key={idx}
            message={msg}
            onNavigateEvent={(eid) => navigate(`/events/${eid}`)}
            onChoiceSelect={handleChoiceSelect}
          />
        ))}
        {chatMutation.isPending && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-green-100 text-green-600 flex items-center justify-center flex-shrink-0">
              <Bot size={16} />
            </div>
            <div className="bg-gray-100 px-4 py-2.5 rounded-2xl rounded-tl-sm flex items-center gap-2">
              <Loader2 size={16} className="animate-spin text-indigo-600" />
              <span className="text-sm text-gray-500">Agent 思考中...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Pending files preview */}
      {pendingFiles.length > 0 && (
        <div className="border-t border-gray-100 px-1 py-2 flex-shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {pendingFiles.map((file, idx) => (
              <span key={idx} className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-gray-100 rounded-lg text-xs text-gray-700">
                {getFileIcon(file)}
                <span className="max-w-[150px] truncate">{file.name}</span>
                <button
                  onClick={() => setPendingFiles((prev) => prev.filter((_, i) => i !== idx))}
                  className="ml-0.5 text-gray-400 hover:text-red-500"
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Input bar — textarea for Shift+Enter multiline */}
      <div className="border-t border-gray-200 pt-3 flex-shrink-0">
        <div className="flex gap-2 items-end">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.xlsx,.xls,.csv,.pdf"
            onChange={(e) => {
              setPendingFiles((prev) => [...prev, ...Array.from(e.target.files || [])]);
              e.target.value = '';
            }}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={chatMutation.isPending}
            className="p-2.5 text-gray-400 hover:text-indigo-600 transition-colors disabled:opacity-50 rounded-lg hover:bg-gray-100"
            title="上传文件（图片/Excel/PDF）"
          >
            <Paperclip size={20} />
          </button>
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onPaste={(e) => {
                const items = e.clipboardData?.items;
                if (!items) return;
                const pastedFiles: File[] = [];
                for (let i = 0; i < items.length; i++) {
                  if (items[i].kind === 'file') {
                    const file = items[i].getAsFile();
                    if (file) pastedFiles.push(file);
                  }
                }
                if (pastedFiles.length > 0) {
                  e.preventDefault();
                  setPendingFiles((prev) => [...prev, ...pastedFiles]);
                }
              }}
              placeholder="描述你的需求，或上传活动海报/名单...（Shift+Enter 换行）"
              disabled={chatMutation.isPending}
              rows={1}
              className="w-full px-4 py-2.5 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-50 resize-none overflow-hidden"
            />
          </div>
          <button
            onClick={handleSend}
            disabled={(!input.trim() && pendingFiles.length === 0) || chatMutation.isPending}
            className="px-4 py-2.5 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={18} />
          </button>
        </div>
        <div className="text-[10px] text-gray-400 mt-1 ml-12">
          Enter 发送 · Shift+Enter 换行
        </div>
      </div>
    </div>
  );
}
