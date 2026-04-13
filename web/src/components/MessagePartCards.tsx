/**
 * MessagePartCards — Domain-specific card components for structured message parts.
 *
 * Each card type renders a specific kind of data returned by the agent's tools.
 * Cards are deterministic renderers — only the data is dynamic.
 *
 * Supported types:
 * - seat_map: Seat layout stats with zone summary
 * - attendee_table: Scrollable attendee roster
 * - event_card: Event summary with key details
 * - page_preview: Iframe preview for H5 pages
 * - confirmation: Action approval buttons
 * - file_link: Downloadable file badge
 * - stats: Key-value statistics grid
 */
import { useState } from 'react';
import {
  LayoutGrid, Users, Calendar, MapPin,
  ExternalLink, FileDown, CheckCircle,
  ChevronDown, ChevronUp, Eye,
} from 'lucide-react';
import type { MessagePart } from '../lib/api';

interface CardProps {
  part: MessagePart;
  compact?: boolean;
  onNavigateEvent?: (eventId: string) => void;
  onChoiceSelect?: (value: string) => void;
}

// ── Seat Map Card ──────────────────────────────────────────────
function SeatMapCard({ part, compact, onNavigateEvent }: CardProps) {
  const stats = part.stats || {};
  const zones = stats.zones || [];
  const total = stats.total || 0;
  const assigned = stats.assigned || 0;
  const pct = total > 0 ? Math.round((assigned / total) * 100) : 0;

  return (
    <div className={`border border-blue-200 rounded-lg overflow-hidden bg-gradient-to-br from-blue-50 to-white ${
      compact ? 'text-[11px]' : 'text-xs'
    }`}>
      <div className="px-3 py-2 bg-blue-100/60 flex items-center gap-1.5 font-medium text-blue-800">
        <LayoutGrid size={compact ? 12 : 14} />
        座位布局 {stats.layout_type ? `(${stats.layout_type})` : ''}
      </div>
      <div className="px-3 py-2 space-y-1.5">
        {/* Stats row */}
        <div className="flex gap-3">
          <span>总座位: <strong>{total}</strong></span>
          <span>已分配: <strong className="text-green-600">{assigned}</strong></span>
          <span>空闲: <strong className="text-orange-600">{stats.unassigned || total - assigned}</strong></span>
        </div>
        {/* Progress bar */}
        <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
        {/* Zones */}
        {zones.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {zones.map((z: string, i: number) => (
              <span key={i} className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px]">
                {z}
              </span>
            ))}
          </div>
        )}
        {/* Navigate button */}
        {part.event_id && onNavigateEvent && (
          <button
            onClick={() => onNavigateEvent(part.event_id)}
            className="flex items-center gap-1 text-blue-600 hover:text-blue-800 font-medium mt-1"
          >
            <Eye size={compact ? 10 : 12} />
            查看座位图
          </button>
        )}
      </div>
    </div>
  );
}

// ── Attendee Table Card ────────────────────────────────────────
function AttendeeTableCard({ part, compact }: CardProps) {
  const [expanded, setExpanded] = useState(false);
  const rows = part.rows || [];
  const total = part.total || rows.length;
  const shown = expanded ? rows : rows.slice(0, 5);

  return (
    <div className={`border border-gray-200 rounded-lg overflow-hidden ${
      compact ? 'text-[11px]' : 'text-xs'
    }`}>
      <div className="px-3 py-2 bg-gray-50 flex items-center gap-1.5 font-medium text-gray-700">
        <Users size={compact ? 12 : 14} />
        {part.title || '参会者列表'} ({total})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 text-gray-500">
              <th className="px-2 py-1 text-left font-medium">姓名</th>
              <th className="px-2 py-1 text-left font-medium">角色</th>
              <th className="px-2 py-1 text-left font-medium">组织</th>
              {rows.some((r: any) => r.seat_label) && (
                <th className="px-2 py-1 text-left font-medium">座位</th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {shown.map((row: any, i: number) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-2 py-1 font-medium text-gray-800">{row.name}</td>
                <td className="px-2 py-1 text-gray-600">{row.role || '-'}</td>
                <td className="px-2 py-1 text-gray-600">{row.organization || '-'}</td>
                {rows.some((r: any) => r.seat_label) && (
                  <td className="px-2 py-1 text-gray-600">{row.seat_label || '-'}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 5 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full py-1 text-center text-blue-600 hover:bg-blue-50 flex items-center justify-center gap-1"
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {expanded ? '收起' : `展开全部 (${total})`}
        </button>
      )}
    </div>
  );
}

// ── Event Card ─────────────────────────────────────────────────
function EventCard({ part, compact, onNavigateEvent }: CardProps) {
  const ev = part.event || {};
  const statusColors: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-600',
    active: 'bg-green-100 text-green-700',
    completed: 'bg-blue-100 text-blue-700',
    cancelled: 'bg-red-100 text-red-600',
  };
  const statusBg = statusColors[ev.status] || 'bg-gray-100 text-gray-600';

  return (
    <div className={`border border-indigo-200 rounded-lg overflow-hidden bg-gradient-to-br from-indigo-50 to-white ${
      compact ? 'text-[11px]' : 'text-xs'
    }`}>
      <div className="px-3 py-2 flex items-center justify-between">
        <span className="font-semibold text-gray-800 text-sm">{ev.name || '活动'}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusBg}`}>
          {ev.status || '-'}
        </span>
      </div>
      <div className="px-3 pb-2 space-y-1 text-gray-600">
        <div className="flex items-center gap-1.5">
          <Calendar size={11} className="text-gray-400" />
          {ev.date || '未定'}
        </div>
        <div className="flex items-center gap-1.5">
          <MapPin size={11} className="text-gray-400" />
          {ev.location || '未定'}
        </div>
        <div className="flex gap-3 mt-1">
          {ev.layout_type && <span>布局: {ev.layout_type}</span>}
          {ev.attendee_count > 0 && <span>参会者: {ev.attendee_count}</span>}
          {ev.seat_count > 0 && <span>座位: {ev.seat_count}</span>}
        </div>
        {ev.id && onNavigateEvent && (
          <button
            onClick={() => onNavigateEvent(ev.id)}
            className="flex items-center gap-1 text-indigo-600 hover:text-indigo-800 font-medium mt-1"
          >
            <ExternalLink size={compact ? 10 : 12} />
            打开活动详情
          </button>
        )}
      </div>
    </div>
  );
}

// ── Page Preview Card ──────────────────────────────────────────
function PagePreviewCard({ part, compact }: CardProps) {
  return (
    <div className={`border border-gray-200 rounded-lg overflow-hidden ${
      compact ? 'text-[11px]' : 'text-xs'
    }`}>
      <div className="px-3 py-2 bg-gray-50 flex items-center justify-between">
        <span className="font-medium text-gray-700 flex items-center gap-1.5">
          <Eye size={compact ? 12 : 14} />
          {part.title || '页面预览'}
        </span>
        {part.url && (
          <a
            href={part.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:text-blue-800 flex items-center gap-0.5"
          >
            <ExternalLink size={10} />
            新窗口
          </a>
        )}
      </div>
      {part.url && (
        <div className="bg-white" style={{ height: compact ? 200 : 300 }}>
          <iframe
            src={part.url}
            className="w-full h-full border-0"
            title={part.title || 'preview'}
            sandbox="allow-scripts allow-same-origin"
          />
        </div>
      )}
      {part.description && (
        <div className="px-3 py-1.5 text-gray-500 bg-gray-50 border-t">
          {part.description}
        </div>
      )}
    </div>
  );
}

// ── Confirmation Card ──────────────────────────────────────────
function ConfirmationCard({ part, compact, onChoiceSelect }: CardProps) {
  const [acted, setActed] = useState(false);
  const actions = part.actions || [];

  if (acted) return null;

  const styleMap: Record<string, string> = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700',
    danger: 'border border-red-300 text-red-600 hover:bg-red-50',
    default: 'border border-gray-300 text-gray-700 hover:bg-gray-50',
  };

  return (
    <div className={`border border-amber-200 rounded-lg overflow-hidden bg-amber-50 ${
      compact ? 'text-[11px]' : 'text-xs'
    }`}>
      <div className="px-3 py-2 text-amber-800 font-medium">
        {part.prompt || '请确认操作'}
      </div>
      <div className="px-3 pb-2 flex gap-2">
        {actions.map((action: any, i: number) => (
          <button
            key={i}
            onClick={() => {
              setActed(true);
              onChoiceSelect?.(action.value || action.label);
            }}
            className={`px-3 py-1 rounded-lg font-medium transition-colors ${
              styleMap[action.style || 'default']
            }`}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── File Link Card ─────────────────────────────────────────────
function FileLinkCard({ part, compact }: CardProps) {
  const sizeStr = part.size
    ? part.size > 1024 * 1024
      ? `${(part.size / 1024 / 1024).toFixed(1)} MB`
      : `${Math.round(part.size / 1024)} KB`
    : '';

  return (
    <a
      href={part.url}
      target="_blank"
      rel="noopener noreferrer"
      className={`inline-flex items-center gap-2 border border-gray-200 rounded-lg px-3 py-2 hover:bg-gray-50 transition-colors ${
        compact ? 'text-[11px]' : 'text-xs'
      }`}
    >
      <FileDown size={compact ? 14 : 16} className="text-gray-400" />
      <div>
        <div className="font-medium text-gray-800">{part.filename || '下载文件'}</div>
        {sizeStr && <div className="text-gray-400">{sizeStr}</div>}
      </div>
    </a>
  );
}

// ── Stats Card ─────────────────────────────────────────────────
function StatsCard({ part, compact }: CardProps) {
  const items = part.items || [];

  return (
    <div className={`border border-gray-200 rounded-lg overflow-hidden ${
      compact ? 'text-[11px]' : 'text-xs'
    }`}>
      <div className="px-3 py-2 bg-gray-50 font-medium text-gray-700 flex items-center gap-1.5">
        <CheckCircle size={compact ? 12 : 14} />
        {part.title || '统计'}
      </div>
      <div className={`grid ${
        items.length <= 3 ? 'grid-cols-3' : 'grid-cols-4'
      } gap-0 divide-x divide-gray-100`}>
        {items.map((item: any, i: number) => (
          <div key={i} className="px-3 py-2 text-center">
            <div className={`font-bold text-lg ${
              item.color === 'green' ? 'text-green-600'
              : item.color === 'red' ? 'text-red-600'
              : item.color === 'blue' ? 'text-blue-600'
              : 'text-gray-800'
            }`}>
              {item.value}
            </div>
            <div className="text-gray-500 mt-0.5">{item.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Dispatcher ────────────────────────────────────────────
export function MessagePartCard(props: CardProps) {
  switch (props.part.type) {
    case 'seat_map':
      return <SeatMapCard {...props} />;
    case 'attendee_table':
      return <AttendeeTableCard {...props} />;
    case 'event_card':
      return <EventCard {...props} />;
    case 'page_preview':
      return <PagePreviewCard {...props} />;
    case 'confirmation':
      return <ConfirmationCard {...props} />;
    case 'file_link':
      return <FileLinkCard {...props} />;
    case 'stats':
      return <StatsCard {...props} />;
    default:
      return null;
  }
}

/**
 * Render a list of message parts as stacked cards.
 */
export function MessageParts({
  parts,
  compact,
  onNavigateEvent,
  onChoiceSelect,
}: {
  parts: MessagePart[];
  compact?: boolean;
  onNavigateEvent?: (eventId: string) => void;
  onChoiceSelect?: (value: string) => void;
}) {
  if (!parts || parts.length === 0) return null;

  return (
    <div className={`mt-2 space-y-2 ${compact ? 'space-y-1.5' : 'space-y-2'}`}>
      {parts.map((part, i) => (
        <MessagePartCard
          key={i}
          part={part}
          compact={compact}
          onNavigateEvent={onNavigateEvent}
          onChoiceSelect={onChoiceSelect}
        />
      ))}
    </div>
  );
}
