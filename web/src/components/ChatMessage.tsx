/**
 * ChatMessage — Shared rich message renderer for agent conversations.
 *
 * Features:
 * - Markdown rendering (react-markdown)
 * - Tool call status indicators
 * - HITL quick-reply buttons (structured from API)
 * - File attachment badges
 */
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { visit } from 'unist-util-visit';
import {
  Bot, User, FileImage, FileSpreadsheet, FileText,
  ExternalLink, Wrench, CheckCircle2, XCircle,
  ThumbsUp, ThumbsDown, Activity,
} from 'lucide-react';
import type { MessagePart } from '../lib/api';
import { MessageParts } from './MessagePartCards';

/**
 * Inline remark plugin: convert soft line breaks (\n) to hard breaks (<br>).
 * Equivalent to remark-breaks — avoids extra npm dependency.
 */
function remarkBreaks() {
  return (tree: any) => {
    visit(tree, 'text', (node: any, index: number | undefined, parent: any) => {
      if (!parent || index === undefined) return;
      const parts = node.value.split('\n');
      if (parts.length <= 1) return;
      const newChildren: any[] = [];
      parts.forEach((part: string, i: number) => {
        if (i > 0) newChildren.push({ type: 'break' });
        if (part) newChildren.push({ type: 'text', value: part });
      });
      parent.children.splice(index, 1, ...newChildren);
    });
  };
}

export interface ToolCallInfo {
  tool_name: string;
  tool_name_zh: string;
  status: string;
  summary: string;
}

export interface ReflectionInfo {
  score: number;
  passed: boolean;
  issues: string[];
  suggestions: string[];
  metrics: Record<string, any>;
}

export interface QuickReplyData {
  label: string;
  value: string;
  style?: 'primary' | 'default' | 'danger';
}

export interface ChatMessageData {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: Date;
  attachments?: { name: string; type: string }[];
  eventId?: string;
  toolCalls?: ToolCallInfo[];
  reflection?: ReflectionInfo;
  /** Structured quick-reply buttons from API */
  quickReplies?: QuickReplyData[];
  /** Legacy: text-parsed choices (fallback) */
  choices?: string[];
  /** Structured UI card parts from agent tools */
  parts?: MessagePart[];
}

interface ChatMessageProps {
  message: ChatMessageData;
  compact?: boolean;  // SubAgentPanel uses compact mode
  onNavigateEvent?: (eventId: string) => void;
  onChoiceSelect?: (choice: string) => void;
  onFeedback?: (feedback: number) => void;
}

function AttachmentBadge({ att, compact }: { att: { name: string; type: string }; compact?: boolean }) {
  const iconSize = compact ? 10 : 12;
  const Icon = att.type === 'image' ? FileImage
    : att.type === 'excel' ? FileSpreadsheet
    : FileText;
  return (
    <span className={`inline-flex items-center gap-1 bg-indigo-100 text-indigo-700 rounded-full ${
      compact ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs'
    }`}>
      <Icon size={iconSize} />
      {compact && att.name.length > 15 ? att.name.slice(0, 12) + '...' : att.name}
    </span>
  );
}

function ToolCallList({ calls, compact }: { calls: ToolCallInfo[]; compact?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? calls : calls.slice(0, 3);
  return (
    <div className={`mt-1.5 border border-gray-200 rounded-lg overflow-hidden ${
      compact ? 'text-[10px]' : 'text-xs'
    }`}>
      <div className="bg-gray-50 px-2 py-1 font-medium text-gray-600 flex items-center gap-1">
        <Wrench size={compact ? 10 : 12} />
        工具调用 ({calls.length})
      </div>
      <div className="divide-y divide-gray-100">
        {shown.map((tc, i) => (
          <div key={i} className="px-2 py-1 flex items-center gap-1.5">
            {tc.status === 'success' ? (
              <CheckCircle2 size={compact ? 10 : 12} className="text-green-500 flex-shrink-0" />
            ) : (
              <XCircle size={compact ? 10 : 12} className="text-red-500 flex-shrink-0" />
            )}
            <span className="font-medium text-gray-700">{tc.tool_name_zh}</span>
            <span className="text-gray-400 truncate">{tc.summary}</span>
          </div>
        ))}
      </div>
      {calls.length > 3 && !expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full text-center py-0.5 text-indigo-600 hover:bg-indigo-50 text-[10px]"
        >
          展开全部 ({calls.length})
        </button>
      )}
    </div>
  );
}

/** Styled quick-reply buttons from structured API data. */
function QuickReplyButtons({
  replies,
  onSelect,
  compact,
}: {
  replies: QuickReplyData[];
  onSelect?: (value: string) => void;
  compact?: boolean;
}) {
  const [clicked, setClicked] = useState(false);
  if (clicked) return null; // Hide after click

  const styleMap = {
    primary: compact
      ? 'bg-indigo-600 text-white hover:bg-indigo-700 px-2.5 py-1 text-[11px]'
      : 'bg-indigo-600 text-white hover:bg-indigo-700 px-4 py-1.5 text-xs',
    default: compact
      ? 'border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 px-2.5 py-1 text-[11px]'
      : 'border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 px-4 py-1.5 text-xs',
    danger: compact
      ? 'border border-red-300 text-red-600 bg-white hover:bg-red-50 px-2.5 py-1 text-[11px]'
      : 'border border-red-300 text-red-600 bg-white hover:bg-red-50 px-4 py-1.5 text-xs',
  };

  return (
    <div className={`mt-2 flex flex-wrap ${compact ? 'gap-1.5' : 'gap-2'}`}>
      {replies.map((r, i) => (
        <button
          key={i}
          onClick={() => {
            setClicked(true);
            onSelect?.(r.value || r.label);
          }}
          className={`rounded-lg font-medium transition-colors ${
            styleMap[r.style || 'default']
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

/** Legacy text-parsed choice buttons (fallback). */
function ChoiceButtons({
  choices,
  onSelect,
  compact,
}: {
  choices: string[];
  onSelect?: (choice: string) => void;
  compact?: boolean;
}) {
  return (
    <div className={`mt-2 flex flex-wrap gap-1.5 ${compact ? 'gap-1' : 'gap-1.5'}`}>
      {choices.map((c, i) => (
        <button
          key={i}
          onClick={() => onSelect?.(c)}
          className={`border border-indigo-300 text-indigo-700 bg-indigo-50 hover:bg-indigo-100 rounded-lg font-medium transition-colors ${
            compact ? 'px-2 py-0.5 text-[11px]' : 'px-3 py-1 text-xs'
          }`}
        >
          {c}
        </button>
      ))}
    </div>
  );
}

function ReflectionBar({ reflection, compact }: { reflection: ReflectionInfo; compact?: boolean }) {
  const pct = Math.round(reflection.score * 100);
  const color = pct >= 80 ? 'green' : pct >= 50 ? 'yellow' : 'red';
  const barColors = {
    green: 'bg-green-400',
    yellow: 'bg-yellow-400',
    red: 'bg-red-400',
  };
  const textColors = {
    green: 'text-green-700',
    yellow: 'text-yellow-700',
    red: 'text-red-700',
  };
  return (
    <div className={`mt-1 ${compact ? 'text-[9px]' : 'text-[10px]'}`}>
      <div className="flex items-center gap-1.5">
        <Activity size={compact ? 9 : 10} className={textColors[color]} />
        <span className={`font-medium ${textColors[color]}`}>
          质量 {pct}%
        </span>
        <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full ${barColors[color]} rounded-full transition-all`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      {reflection.issues.length > 0 && (
        <div className="mt-0.5 text-gray-500">
          {reflection.issues.map((issue, i) => (
            <div key={i}>⚠ {issue}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function FeedbackButtons({
  onFeedback,
  compact,
}: {
  onFeedback: (feedback: number) => void;
  compact?: boolean;
}) {
  const [voted, setVoted] = useState<number | null>(null);
  if (voted !== null) {
    return (
      <span className={`${compact ? 'text-[9px]' : 'text-[10px]'} text-gray-400 mt-0.5 inline-block`}>
        {voted > 0 ? '👍 已记录' : '👎 已记录，Agent 将改进'}
      </span>
    );
  }
  return (
    <div className={`mt-1 flex items-center gap-1 ${compact ? 'gap-0.5' : 'gap-1'}`}>
      <button
        onClick={() => { setVoted(1); onFeedback(1); }}
        className="p-0.5 rounded hover:bg-green-50 text-gray-400 hover:text-green-600 transition-colors"
        title="有帮助"
      >
        <ThumbsUp size={compact ? 10 : 12} />
      </button>
      <button
        onClick={() => { setVoted(-1); onFeedback(-1); }}
        className="p-0.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors"
        title="需改进"
      >
        <ThumbsDown size={compact ? 10 : 12} />
      </button>
    </div>
  );
}

export function ChatMessage({ message, compact, onNavigateEvent, onChoiceSelect, onFeedback }: ChatMessageProps) {
  const isUser = message.role === 'user';
  const avatarSize = compact ? 'w-5 h-5' : 'w-8 h-8';
  const iconSize = compact ? 12 : 16;
  const maxWidth = compact ? 'max-w-[85%]' : 'max-w-[70%]';

  return (
    <div className={`flex gap-2 ${compact ? 'gap-1.5' : 'gap-3'} ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`${avatarSize} rounded-full flex items-center justify-center flex-shrink-0 ${
        isUser ? 'bg-indigo-100 text-indigo-600' : 'bg-green-100 text-green-600'
      }`}>
        {isUser ? <User size={iconSize} /> : <Bot size={iconSize} />}
      </div>

      {/* Content */}
      <div className={`${maxWidth} ${isUser ? 'text-right' : ''}`}>
        {/* Attachments */}
        {message.attachments && message.attachments.length > 0 && (
          <div className={`flex flex-wrap gap-1 mb-1 ${isUser ? 'justify-end' : ''}`}>
            {message.attachments.map((att, i) => (
              <AttachmentBadge key={i} att={att} compact={compact} />
            ))}
          </div>
        )}

        {/* Message bubble */}
        <div className={`inline-block text-left ${
          compact
            ? `px-2.5 py-1.5 rounded-lg text-xs leading-relaxed`
            : `px-4 py-2.5 rounded-2xl text-sm leading-relaxed`
        } ${
          isUser
            ? `bg-indigo-600 text-white ${compact ? '' : 'rounded-tr-sm'}`
            : `bg-gray-100 text-gray-800 ${compact ? '' : 'rounded-tl-sm'}`
        }`}>
          {isUser ? (
            // User messages: plain text
            message.content.split('\n').map((line, i) => (
              <span key={i}>
                {line}
                {i < message.content.split('\n').length - 1 && <br />}
              </span>
            ))
          ) : (
            // Assistant messages: render as Markdown
            <div className={`prose prose-sm max-w-none ${compact ? 'prose-xs' : ''} prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-headings:my-1.5 prose-pre:my-1 prose-pre:bg-gray-800 prose-pre:text-gray-100 prose-code:text-indigo-600 prose-code:bg-indigo-50 prose-code:px-1 prose-code:rounded`}>
              <ReactMarkdown remarkPlugins={[remarkBreaks]}>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {/* Tool calls */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <ToolCallList calls={message.toolCalls} compact={compact} />
        )}

        {/* Structured UI card parts */}
        {!isUser && message.parts && message.parts.length > 0 && (
          <MessageParts
            parts={message.parts}
            compact={compact}
            onNavigateEvent={onNavigateEvent}
            onChoiceSelect={onChoiceSelect}
          />
        )}

        {/* Structured quick-reply buttons (preferred) */}
        {!isUser && message.quickReplies && message.quickReplies.length > 0 && (
          <QuickReplyButtons replies={message.quickReplies} onSelect={onChoiceSelect} compact={compact} />
        )}

        {/* Legacy HITL choice buttons (fallback when no quickReplies) */}
        {!isUser && !message.quickReplies?.length && message.choices && message.choices.length > 0 && (
          <ChoiceButtons choices={message.choices} onSelect={onChoiceSelect} compact={compact} />
        )}

        {/* Event link */}
        {!isUser && message.eventId && onNavigateEvent && (
          <button
            onClick={() => onNavigateEvent(message.eventId!)}
            className={`mt-1 inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-800 font-medium ${
              compact ? 'text-[10px]' : 'text-xs'
            }`}
          >
            <ExternalLink size={compact ? 10 : 12} />
            打开活动详情
          </button>
        )}

        {/* Self-evolution: reflection quality bar */}
        {!isUser && message.reflection && (
          <ReflectionBar reflection={message.reflection} compact={compact} />
        )}

        {/* Self-evolution: feedback buttons (👍👎) */}
        {!isUser && onFeedback && message.toolCalls && message.toolCalls.length > 0 && (
          <FeedbackButtons onFeedback={onFeedback} compact={compact} />
        )}
      </div>
    </div>
  );
}

/**
 * Parse HITL choices from agent message (legacy fallback).
 *
 * Detects patterns like:
 * - "1. 选项A\n2. 选项B\n3. 选项C"
 * - Lines ending with ? followed by lines starting with - or ·
 */
export function parseChoices(content: string): string[] {
  const choices: string[] = [];

  // Pattern 1: numbered list after a question (1. / 2. / 3.)
  const numberedMatch = content.match(
    /(?:请(?:选择|确认|决定)|以下.*选项|你(?:希望|想要|需要).*(?:哪|什么|如何)).*?\n((?:\s*\d+[.、)）]\s*.+\n?){2,})/s
  );
  if (numberedMatch) {
    const lines = numberedMatch[1].trim().split('\n');
    for (const line of lines) {
      const cleaned = line.replace(/^\s*\d+[.、)）]\s*/, '').trim();
      if (cleaned) choices.push(cleaned);
    }
    if (choices.length >= 2) return choices;
  }

  // Pattern 2: bullet list after a question (- or · or *)
  const bulletMatch = content.match(
    /(?:请(?:选择|确认|决定)|以下.*选项|你(?:希望|想要|需要).*(?:哪|什么|如何)).*?\n((?:\s*[-·*]\s*.+\n?){2,})/s
  );
  if (bulletMatch) {
    const lines = bulletMatch[1].trim().split('\n');
    for (const line of lines) {
      const cleaned = line.replace(/^\s*[-·*]\s*/, '').trim();
      if (cleaned) choices.push(cleaned);
    }
    if (choices.length >= 2) return choices;
  }

  return [];
}
