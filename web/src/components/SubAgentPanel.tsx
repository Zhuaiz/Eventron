/**
 * SubAgentPanel — Reusable scoped AI assistant panel for each tab.
 *
 * Features:
 * - SSE streaming with real-time tool call progress
 * - Markdown rendering via ChatMessage
 * - Shift+Enter multiline input
 * - Tool call status indicators
 * - HITL interactive choice buttons
 * - Clear button (manual only — no auto-clear on tab switch)
 * - File upload support
 * - Collapsible sidebar layout
 */
import { useState, useRef, useEffect, useCallback, DragEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Bot, Send, Paperclip, X, ChevronRight, ChevronLeft,
  FileImage, FileText, Loader2, Trash2, Upload, FolderOpen,
  CheckCircle, XCircle,
} from 'lucide-react';
import { apiClient } from '../lib/api';
import { ChatMessage, parseChoices } from './ChatMessage';
import type { ChatMessageData, ToolCallInfo, QuickReplyData } from './ChatMessage';

interface EventFileEntry {
  id: string;
  filename: string;
  type: string;
  content_type: string;
  size: number;
  uploaded_at: string;
}

interface StreamingToolCall {
  tool_name: string;
  tool_name_zh: string;
  status: 'running' | 'success' | 'error';
  summary?: string;
}

interface SubAgentPanelProps {
  eventId: string;
  scope: string;
  title: string;
  placeholder?: string;
  welcomeMessage: string;
}

export function SubAgentPanel({
  eventId,
  scope,
  title,
  placeholder = '描述你的需求...（Shift+Enter 换行）',
  welcomeMessage,
}: SubAgentPanelProps) {
  // ── Persist chat per event+scope in sessionStorage ───────
  const STORAGE_KEY = `eventron_sub_${eventId}_${scope}`;

  const loadPersistedState = () => {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw) as {
        messages: ChatMessageData[];
        sessionId: string | null;
      };
    } catch {
      return null;
    }
  };

  const persisted = loadPersistedState();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [messages, setMessages] = useState<ChatMessageData[]>(
    persisted?.messages?.length
      ? persisted.messages
      : [{ role: 'assistant', content: welcomeMessage }],
  );
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(persisted?.sessionId ?? null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  // Save to sessionStorage on change
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
        messages,
        sessionId,
      }));
    } catch {
      // ignore
    }
  }, [messages, sessionId, STORAGE_KEY]);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const dragCounterRef = useRef(0);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingTools, setStreamingTools] = useState<StreamingToolCall[]>([]);
  const [thinkingStep, setThinkingStep] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const filePickerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const queryClient = useQueryClient();

  // Fetch existing event files for the picker
  const { data: eventFiles = [] } = useQuery({
    queryKey: ['event-files', eventId],
    queryFn: () => apiClient.listEventFiles(eventId) as Promise<EventFileEntry[]>,
    enabled: showFilePicker,
  });

  // Close popover on outside click
  useEffect(() => {
    if (!showFilePicker) return;
    const handler = (e: MouseEvent) => {
      if (filePickerRef.current && !filePickerRef.current.contains(e.target as Node)) {
        setShowFilePicker(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showFilePicker]);

  // Add an existing event file to pending (fetches as blob)
  const addExistingFile = async (entry: EventFileEntry) => {
    setShowFilePicker(false);
    try {
      const url = apiClient.getEventFileUrl(eventId, entry.id);
      const resp = await fetch(url, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem('token') || ''}`,
        },
      });
      if (!resp.ok) return;
      const blob = await resp.blob();
      const file = new window.File([blob], entry.filename, {
        type: entry.content_type,
      });
      setPendingFiles((p) => [...p, file]);
    } catch {
      // silently ignore fetch errors
    }
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingTools]);

  // Auto-resize textarea
  const adjustHeight = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta || ta.offsetHeight === 0) return;
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
  }, []);

  useEffect(() => { adjustHeight(); }, [input, adjustHeight]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    const ro = new ResizeObserver(() => { adjustHeight(); });
    ro.observe(ta);
    return () => ro.disconnect();
  }, [adjustHeight]);

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

  const handleClear = () => {
    setMessages([{ role: 'assistant', content: welcomeMessage }]);
    setSessionId(null);
    setPendingFiles([]);
    setInput('');
    setStreamingTools([]);
    setThinkingStep(0);
    sessionStorage.removeItem(STORAGE_KEY);
    if (abortRef.current) abortRef.current.abort();
  };

  const doSend = useCallback(async (msg: string, files: File[] = []) => {
    if ((!msg.trim() && files.length === 0) || isStreaming) return;

    const attachments = files.map((f) => ({
      name: f.name,
      type: f.type.startsWith('image/') ? 'image' : f.name.endsWith('.xlsx') ? 'excel' : 'file',
    }));

    setMessages((prev) => [
      ...prev,
      {
        role: 'user' as const,
        content: msg.trim() || `上传了 ${files.length} 个文件`,
        attachments: attachments.length > 0 ? attachments : undefined,
      },
    ]);
    setInput('');
    setPendingFiles([]);
    setIsStreaming(true);
    setStreamingTools([]);
    setThinkingStep(0);

    try {
      const stream = apiClient.streamAgentChat(
        msg.trim() || '请分析这些文件',
        { eventId, sessionId: sessionId || undefined, scope, files },
      );

      for await (const evt of stream) {
        switch (evt.event) {
          case 'thinking':
            setThinkingStep(evt.iteration || 1);
            break;

          case 'tool_start':
            setStreamingTools((prev) => [
              ...prev,
              {
                tool_name: evt.tool_name,
                tool_name_zh: evt.tool_name_zh,
                status: 'running',
              },
            ]);
            break;

          case 'tool_end':
            setStreamingTools((prev) =>
              prev.map((t) =>
                t.tool_name === evt.tool_name && t.status === 'running'
                  ? { ...t, status: evt.status || 'success', summary: evt.summary }
                  : t
              )
            );
            break;

          case 'done': {
            setSessionId(evt.session_id || sessionId);
            const rawQr = (evt.quick_replies || []) as QuickReplyData[];
            const choices = rawQr.length > 0 ? undefined : parseChoices(evt.reply || '') || undefined;
            const rawParts = evt.parts || undefined;
            setMessages((prev) => [
              ...prev,
              {
                role: 'assistant',
                content: evt.reply || '',
                toolCalls: evt.tool_calls as ToolCallInfo[] | undefined,
                quickReplies: rawQr.length > 0 ? rawQr : undefined,
                choices: choices && choices.length > 0 ? choices : undefined,
                reflection: evt.reflection || undefined,
                parts: rawParts,
              },
            ]);
            // Refresh related data
            queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
            queryClient.invalidateQueries({ queryKey: ['attendees', eventId] });
            queryClient.invalidateQueries({ queryKey: ['dashboard', eventId] });
            queryClient.invalidateQueries({ queryKey: ['badge-templates'] });
            break;
          }

          case 'error':
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: `**出错了：** ${evt.message || '请重试'}` },
            ]);
            break;
        }
      }
    } catch (err) {
      // SSE failed — fall back to regular endpoint
      try {
        const data = await apiClient.sendAgentChat(
          msg.trim() || '请分析这些文件',
          { eventId, sessionId: sessionId || undefined, scope, files },
        );
        setSessionId(data.session_id);
        const dataQr = (data.quick_replies || []) as QuickReplyData[];
        const choices = dataQr.length > 0 ? undefined : parseChoices(data.reply) || undefined;
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.reply,
            toolCalls: data.tool_calls as ToolCallInfo[] | undefined,
            quickReplies: dataQr.length > 0 ? dataQr : undefined,
            choices: choices && choices.length > 0 ? choices : undefined,
            parts: data.parts || undefined,
          },
        ]);
        queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
        queryClient.invalidateQueries({ queryKey: ['attendees', eventId] });
      } catch (fallbackErr) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `**出错了：** ${fallbackErr instanceof Error ? fallbackErr.message : '请重试'}` },
        ]);
      }
    } finally {
      setIsStreaming(false);
      setStreamingTools([]);
      setThinkingStep(0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, eventId, scope, isStreaming]);

  const handleSend = () => {
    doSend(input, [...pendingFiles]);
  };

  const handleChoiceSelect = (choice: string) => {
    doSend(choice);
  };

  if (isCollapsed) {
    return (
      <div
        onClick={() => setIsCollapsed(false)}
        className="w-10 flex-shrink-0 bg-indigo-50 border-l border-gray-200 flex flex-col items-center justify-center cursor-pointer hover:bg-indigo-100 transition-colors"
      >
        <ChevronLeft size={16} className="text-indigo-600 mb-2" />
        <div className="writing-mode-vertical text-xs text-indigo-600 font-medium" style={{ writingMode: 'vertical-rl' }}>
          {title}
        </div>
      </div>
    );
  }

  return (
    <div
      className="w-80 border-l border-gray-200 bg-white flex flex-col flex-shrink-0 relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-50 bg-indigo-50/80 border-2 border-dashed border-indigo-400 rounded-lg flex flex-col items-center justify-center pointer-events-none">
          <Upload size={28} className="text-indigo-500 mb-1" />
          <p className="text-indigo-600 font-medium text-xs">松开即可上传</p>
          <p className="text-indigo-400 text-[10px] mt-0.5">图片 / Excel / PDF</p>
        </div>
      )}
      {/* Header */}
      <div className="px-3 py-2 border-b border-gray-200 flex items-center justify-between bg-indigo-50">
        <div className="flex items-center gap-2">
          <Bot size={16} className="text-indigo-600" />
          <span className="text-sm font-semibold text-indigo-700">{title}</span>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            onClick={handleClear}
            className="p-1 hover:bg-indigo-100 rounded transition-colors"
            title="清空对话"
          >
            <Trash2 size={13} className="text-indigo-400 hover:text-indigo-600" />
          </button>
          <button onClick={() => setIsCollapsed(true)} className="p-1 hover:bg-indigo-100 rounded">
            <ChevronRight size={14} className="text-indigo-600" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
        {messages.map((msg, idx) => (
          <ChatMessage
            key={idx}
            message={msg}
            compact
            onChoiceSelect={handleChoiceSelect}
            onFeedback={(fb) => {
              apiClient.sendAgentFeedback(eventId, fb).catch(() => {});
            }}
          />
        ))}

        {/* Streaming progress indicator */}
        {isStreaming && (
          <div className="space-y-1.5">
            {/* Tool call progress */}
            {streamingTools.map((tc, idx) => (
              <div key={idx} className="flex items-center gap-1.5 px-2.5 py-1 bg-gray-50 rounded-lg">
                {tc.status === 'running' ? (
                  <Loader2 size={11} className="animate-spin text-indigo-500 flex-shrink-0" />
                ) : tc.status === 'success' ? (
                  <CheckCircle size={11} className="text-green-500 flex-shrink-0" />
                ) : (
                  <XCircle size={11} className="text-red-500 flex-shrink-0" />
                )}
                <span className="text-[10px] text-gray-600 truncate">
                  {tc.tool_name_zh}
                </span>
                {tc.status === 'success' && tc.summary && (
                  <span className="text-[9px] text-gray-400 truncate ml-auto max-w-[120px]">
                    {tc.summary}
                  </span>
                )}
              </div>
            ))}

            {/* Current thinking state */}
            <div className="flex gap-2">
              <div className="bg-gray-100 px-2.5 py-1.5 rounded-lg flex items-center gap-1.5">
                <Loader2 size={12} className="animate-spin text-indigo-600" />
                <span className="text-[10px] text-gray-500">
                  {streamingTools.length > 0
                    ? `执行中...（步骤 ${thinkingStep}）`
                    : '思考中...'
                  }
                </span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Pending files */}
      {pendingFiles.length > 0 && (
        <div className="px-3 py-1.5 border-t border-gray-100 flex flex-wrap gap-1.5">
          {pendingFiles.map((f, i) => (
            <span key={i} className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-gray-100 rounded text-[10px] group">
              {f.type.startsWith('image/') ? (
                <img
                  src={URL.createObjectURL(f)}
                  className="w-8 h-8 rounded object-cover"
                  alt={f.name}
                />
              ) : (
                <FileText size={10} className="text-gray-400" />
              )}
              {f.name.length > 10 ? f.name.slice(0, 8) + '...' : f.name}
              <button onClick={() => setPendingFiles((p) => p.filter((_, j) => j !== i))} className="text-gray-400 hover:text-red-500">
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input — textarea for Shift+Enter */}
      <div className="border-t border-gray-200 p-2">
        <div className="flex gap-1.5 items-end">
          <input ref={fileInputRef} type="file" multiple accept="image/*,.xlsx,.xls,.csv,.pdf" onChange={(e) => {
            setPendingFiles((p) => [...p, ...Array.from(e.target.files || [])]);
            e.target.value = '';
            setShowFilePicker(false);
          }} className="hidden" />
          <div className="relative" ref={filePickerRef}>
            <button
              onClick={() => setShowFilePicker((v) => !v)}
              disabled={isStreaming}
              className="p-1.5 text-gray-400 hover:text-indigo-600 transition-colors disabled:opacity-50"
            >
              <Paperclip size={14} />
            </button>
            {showFilePicker && (
              <div className="absolute bottom-full left-0 mb-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-30 overflow-hidden">
                {/* Upload new */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-indigo-600 hover:bg-indigo-50 border-b border-gray-100"
                >
                  <Upload size={13} />
                  从本地上传新文件
                </button>
                {/* Existing event files */}
                {eventFiles.length > 0 ? (
                  <div className="max-h-36 overflow-y-auto">
                    <div className="px-3 py-1.5 text-[10px] text-gray-400 font-semibold uppercase tracking-wider bg-gray-50">
                      已上传文件
                    </div>
                    {(eventFiles as EventFileEntry[]).map((f) => (
                      <button
                        key={f.id}
                        onClick={() => addExistingFile(f)}
                        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 transition-colors"
                      >
                        {f.type === 'image' ? (
                          <FileImage size={12} className="text-blue-400 flex-shrink-0" />
                        ) : (
                          <FileText size={12} className="text-gray-400 flex-shrink-0" />
                        )}
                        <span className="truncate flex-1 text-left">
                          {f.filename}
                        </span>
                        <span className="text-[9px] text-gray-400 flex-shrink-0">
                          {f.size > 1024 * 1024
                            ? `${(f.size / 1024 / 1024).toFixed(1)}M`
                            : `${Math.round(f.size / 1024)}K`}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="px-3 py-2 text-[10px] text-gray-400 text-center">
                    暂无已上传文件
                  </div>
                )}
              </div>
            )}
          </div>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
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
                setPendingFiles((p) => [...p, ...pastedFiles]);
              }
            }}
            placeholder={placeholder}
            disabled={isStreaming}
            rows={1}
            className="flex-1 px-2 py-1.5 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50 resize-none overflow-hidden"
          />
          <button onClick={handleSend} disabled={(!input.trim() && !pendingFiles.length) || isStreaming}
            className="p-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
