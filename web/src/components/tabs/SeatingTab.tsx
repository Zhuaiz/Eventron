import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Grid3X3, Shuffle, Users, Download, Sparkles, Paintbrush, X } from 'lucide-react';
import { apiClient } from '../../lib/api';
import { SubAgentPanel } from '../SubAgentPanel';

interface SeatingTabProps {
  eventId: string;
  event: {
    venue_rows: number;
    venue_cols: number;
    layout_type: string;
  };
}

interface Seat {
  id: string;
  row_num: number;
  col_num: number;
  label: string;
  seat_type: string;
  zone: string | null;
  attendee_id: string | null;
}

interface Attendee {
  id: string;
  name: string;
  role: string;
  priority: number;
  status: string;
}

interface ZoneSuggestion {
  zone: string;
  min_priority: number;
  rows: number[];
  color: string;
  description: string;
}

const LAYOUT_CONFIG: Record<string, {
  label: string;
  description: string;
  seatShape: string;
}> = {
  theater: { label: '剧院式', description: '面向前方的排列座位', seatShape: 'rounded' },
  classroom: { label: '课桌式', description: '带桌子的排列座位', seatShape: 'rounded-sm' },
  roundtable: { label: '圆桌式', description: '圆桌分组座位', seatShape: 'rounded-full' },
  banquet: { label: '宴会式', description: '宴会桌分组座位', seatShape: 'rounded-full' },
  u_shape: { label: 'U形', description: 'U形会议座位', seatShape: 'rounded' },
};

// Zone colors — used for zone painting and display
const ZONE_PALETTE = [
  { name: '贵宾区', color: '#e2b93b', bg: 'bg-yellow-100 border-yellow-400' },
  { name: '嘉宾区', color: '#4a90d9', bg: 'bg-blue-100 border-blue-400' },
  { name: '媒体区', color: '#9b59b6', bg: 'bg-purple-100 border-purple-400' },
  { name: '工作人员区', color: '#27ae60', bg: 'bg-green-100 border-green-400' },
  { name: '普通区', color: '#6b7280', bg: 'bg-gray-100 border-gray-400' },
];

// Get seat background style based on zone, seat_type, and occupancy
function getSeatStyle(
  seat: Seat,
  attendee: Attendee | undefined,
  zoneColorMap: Map<string, string>,
): { bg: string; border: string } {
  if (seat.seat_type === 'disabled') return { bg: '#e5e7eb', border: '#9ca3af' };
  if (seat.seat_type === 'aisle') return { bg: 'transparent', border: 'transparent' };

  const zoneColor = seat.zone ? zoneColorMap.get(seat.zone) : undefined;

  if (seat.attendee_id && attendee) {
    // Occupied — darken zone color or use green
    if (attendee.priority >= 10) return { bg: '#ddd6fe', border: '#7c3aed' };
    if (attendee.priority >= 5) return { bg: '#fde68a', border: '#d97706' };
    return { bg: '#bbf7d0', border: '#22c55e' };
  }

  if (seat.seat_type === 'reserved') {
    return { bg: zoneColor ? `${zoneColor}33` : '#fef3c7', border: zoneColor || '#d97706' };
  }

  if (zoneColor) {
    return { bg: `${zoneColor}22`, border: `${zoneColor}88` };
  }

  return { bg: '#dbeafe', border: '#93c5fd' };
}

export function SeatingTab({ eventId, event }: SeatingTabProps) {
  const [selectedSeat, setSelectedSeat] = useState<Seat | null>(null);
  const [strategy, setStrategy] = useState('priority_first');
  const [paintMode, setPaintMode] = useState(false);
  const [paintZone, setPaintZone] = useState<string>('贵宾区');
  const [showAgent, setShowAgent] = useState(false);
  const [showZonePanel, setShowZonePanel] = useState(false);
  const queryClient = useQueryClient();

  const { data: seats = [], isLoading: seatsLoading } = useQuery({
    queryKey: ['seats', eventId],
    queryFn: async () => {
      const result = await apiClient.getSeats(eventId);
      return ((result as any).data || result) as Seat[];
    },
  });

  const { data: attendees = [] } = useQuery({
    queryKey: ['attendees', eventId],
    queryFn: async () => {
      const result = await apiClient.getAttendees(eventId);
      return ((result as any).data || result) as Attendee[];
    },
  });

  const createGridMutation = useMutation({
    mutationFn: () =>
      apiClient.createSeatGrid(eventId, event.venue_rows, event.venue_cols),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', eventId] });
    },
  });

  const autoAssignMutation = useMutation({
    mutationFn: () => apiClient.autoAssignSeats(eventId, strategy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', eventId] });
    },
  });

  const updateSeatMutation = useMutation({
    mutationFn: (params: { seatId: string; data: Record<string, unknown> }) =>
      apiClient.updateSeat(eventId, params.seatId, params.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
    },
  });

  const suggestZonesMutation = useMutation({
    mutationFn: () => apiClient.suggestZones(eventId),
    onSuccess: async (data: any) => {
      const zones = data.zones as ZoneSuggestion[];
      // Apply zone suggestions to seats
      for (const zone of zones) {
        for (const seat of seats as Seat[]) {
          if (zone.rows.includes(seat.row_num)) {
            await apiClient.updateSeat(eventId, seat.id, {
              zone: zone.zone,
              seat_type: zone.min_priority >= 10 ? 'reserved' : seat.seat_type,
            });
          }
        }
      }
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
    },
  });

  // Build lookups
  const attendeeMap = useMemo(() => {
    const map = new Map<string, Attendee>();
    (attendees as Attendee[]).forEach((a) => map.set(a.id, a));
    return map;
  }, [attendees]);

  // Build zone color map from actual seat data
  const zoneColorMap = useMemo(() => {
    const map = new Map<string, string>();
    const uniqueZones = new Set<string>();
    (seats as Seat[]).forEach((s) => {
      if (s.zone) uniqueZones.add(s.zone);
    });
    const zoneArr = Array.from(uniqueZones);
    zoneArr.forEach((z, i) => {
      const preset = ZONE_PALETTE.find((p) => p.name === z);
      map.set(z, preset?.color || ZONE_PALETTE[i % ZONE_PALETTE.length].color);
    });
    return map;
  }, [seats]);

  // Unique zone list for legend
  const activeZones = useMemo(() => {
    const zones = new Map<string, number>();
    (seats as Seat[]).forEach((s) => {
      if (s.zone) zones.set(s.zone, (zones.get(s.zone) || 0) + 1);
    });
    return Array.from(zones.entries()).map(([name, count]) => ({
      name,
      count,
      color: zoneColorMap.get(name) || '#6b7280',
    }));
  }, [seats, zoneColorMap]);

  // Build seat grid
  const rows = event.venue_rows || 0;
  const cols = event.venue_cols || 0;

  const seatGrid: (Seat | null)[][] = [];
  for (let r = 0; r < rows; r++) {
    seatGrid[r] = [];
    for (let c = 0; c < cols; c++) {
      seatGrid[r][c] = null;
    }
  }
  (seats as Seat[]).forEach((seat) => {
    const r = seat.row_num - 1;
    const c = seat.col_num - 1;
    if (r >= 0 && r < rows && c >= 0 && c < cols) {
      seatGrid[r][c] = seat;
    }
  });

  const layoutConfig = LAYOUT_CONFIG[event.layout_type] || LAYOUT_CONFIG.theater;
  const hasSeats = (seats as Seat[]).length > 0;
  const assignedCount = (seats as Seat[]).filter((s) => s.attendee_id).length;
  const totalSeats = (seats as Seat[]).length;
  const unassignedAttendees = (attendees as Attendee[]).filter(
    (a) =>
      a.status !== 'cancelled' &&
      !(seats as Seat[]).some((s) => s.attendee_id === a.id)
  );

  const handleSeatClick = (seat: Seat) => {
    if (seat.seat_type === 'disabled' || seat.seat_type === 'aisle') return;

    if (paintMode) {
      // Zone painting mode
      updateSeatMutation.mutate({
        seatId: seat.id,
        data: { zone: paintZone },
      });
      return;
    }
    setSelectedSeat(selectedSeat?.id === seat.id ? null : seat);
  };

  const getSeatLabel = (seat: Seat): string => {
    if (seat.seat_type === 'aisle') return '';
    if (seat.seat_type === 'disabled') return '×';
    if (seat.attendee_id) {
      const att = attendeeMap.get(seat.attendee_id);
      return att?.name || '已分配';
    }
    return seat.label;
  };

  // Calculate cell size
  const maxCellSize = Math.min(Math.floor(800 / cols), Math.floor(500 / rows), 64);
  const cellSize = Math.max(maxCellSize, 32);

  const renderSeatGrid = () => {
    if (!hasSeats) return null;

    return (
      <div className="overflow-auto">
        {/* Stage / Front indicator */}
        <div className="flex justify-center mb-4">
          <div className="px-16 py-2 bg-gray-800 text-white text-sm rounded-t-lg">
            {event.layout_type === 'roundtable' || event.layout_type === 'banquet'
              ? '入口'
              : '讲台 / 前方'}
          </div>
        </div>

        {/* Seat grid */}
        <div className="flex flex-col items-center gap-1">
          {seatGrid.map((row, rIdx) => (
            <div key={rIdx} className="flex items-center gap-1">
              {/* Row label */}
              <div
                className="text-xs text-gray-500 font-mono text-right"
                style={{ width: '28px' }}
              >
                {String.fromCharCode(65 + rIdx)}
              </div>
              {row.map((seat, cIdx) => {
                if (!seat) {
                  return (
                    <div
                      key={cIdx}
                      style={{ width: cellSize, height: cellSize }}
                      className="border border-dashed border-gray-200 rounded flex items-center justify-center text-xs text-gray-300"
                    >
                      ?
                    </div>
                  );
                }
                const att = seat.attendee_id ? attendeeMap.get(seat.attendee_id) : undefined;
                const style = getSeatStyle(seat, att, zoneColorMap);
                const isSelected = selectedSeat?.id === seat.id;
                return (
                  <button
                    key={cIdx}
                    style={{
                      width: cellSize,
                      height: cellSize,
                      backgroundColor: style.bg,
                      borderColor: style.border,
                    }}
                    className={`border-2 ${layoutConfig.seatShape} flex items-center justify-center text-xs font-medium transition-all ${
                      isSelected ? 'ring-2 ring-indigo-500 ring-offset-1 scale-110' : ''
                    } ${paintMode ? 'cursor-crosshair' : 'cursor-pointer'}`}
                    onClick={() => handleSeatClick(seat)}
                    title={`${seat.label}${seat.zone ? ' [' + seat.zone + ']' : ''}${
                      att ? ' - ' + att.name + ' (P' + att.priority + ')' : ''
                    }`}
                  >
                    <span className="truncate px-0.5 leading-tight">
                      {cellSize >= 48
                        ? getSeatLabel(seat)
                        : seat.attendee_id
                          ? getSeatLabel(seat).charAt(0)
                          : seat.label}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
          {/* Column labels */}
          <div className="flex items-center gap-1">
            <div style={{ width: '28px' }} />
            {Array.from({ length: cols }, (_, i) => (
              <div
                key={i}
                style={{ width: cellSize }}
                className="text-xs text-gray-500 font-mono text-center"
              >
                {i + 1}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex gap-6">
      {/* Main content */}
      <div className="flex-1 space-y-6">
        {/* Layout Info Header */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                座位布局 — {layoutConfig.label}
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                {layoutConfig.description} · {rows} 排 × {cols} 列 = {rows * cols} 座
              </p>
            </div>

            {/* Legend */}
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className="flex items-center gap-1">
                <span className="w-3 h-3 rounded" style={{ backgroundColor: '#bbf7d0', border: '1px solid #22c55e' }} />
                已分配
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3 h-3 rounded" style={{ backgroundColor: '#ddd6fe', border: '1px solid #7c3aed' }} />
                高优先
              </span>
              <span className="flex items-center gap-1">
                <span className="w-3 h-3 rounded" style={{ backgroundColor: '#dbeafe', border: '1px solid #93c5fd' }} />
                空座
              </span>
              {activeZones.map((z) => (
                <span key={z.name} className="flex items-center gap-1">
                  <span
                    className="w-3 h-3 rounded"
                    style={{ backgroundColor: `${z.color}33`, border: `1px solid ${z.color}` }}
                  />
                  {z.name} ({z.count})
                </span>
              ))}
            </div>
          </div>

          {/* Actions Bar */}
          <div className="flex flex-wrap gap-3 items-center">
            {!hasSeats && rows > 0 && cols > 0 && (
              <button
                onClick={() => createGridMutation.mutate()}
                disabled={createGridMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium disabled:opacity-50"
              >
                <Grid3X3 size={18} />
                {createGridMutation.isPending ? '生成中...' : '生成座位'}
              </button>
            )}
            {hasSeats && (
              <>
                {/* Auto-assign */}
                <div className="flex items-center gap-2">
                  <select
                    value={strategy}
                    onChange={(e) => setStrategy(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="random">随机分配</option>
                    <option value="priority_first">优先级排座（前排居中）</option>
                    <option value="by_department">按部门分组</option>
                    <option value="by_zone">按分区匹配</option>
                  </select>
                  <button
                    onClick={() => autoAssignMutation.mutate()}
                    disabled={autoAssignMutation.isPending || unassignedAttendees.length === 0}
                    className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium disabled:opacity-50"
                  >
                    <Shuffle size={18} />
                    {autoAssignMutation.isPending ? '分配中...' : '自动排座'}
                  </button>
                </div>

                {/* Zone tools */}
                <div className="flex items-center gap-2 border-l pl-3 ml-1">
                  <button
                    onClick={() => suggestZonesMutation.mutate()}
                    disabled={suggestZonesMutation.isPending}
                    className="flex items-center gap-2 px-3 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors text-sm font-medium disabled:opacity-50"
                    title="根据参会人优先级自动规划分区"
                  >
                    <Sparkles size={16} />
                    {suggestZonesMutation.isPending ? 'AI分区中...' : 'AI智能分区'}
                  </button>
                  <button
                    onClick={() => {
                      setPaintMode(!paintMode);
                      setShowZonePanel(!showZonePanel && !paintMode);
                    }}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      paintMode
                        ? 'bg-indigo-600 text-white'
                        : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <Paintbrush size={16} />
                    {paintMode ? '退出涂色' : '手动分区'}
                  </button>
                </div>

                {/* Stats */}
                <div className="flex items-center gap-1 text-sm text-gray-500 ml-auto">
                  <Users size={16} />
                  已分配 {assignedCount}/{totalSeats} · 待分配 {unassignedAttendees.length} 人
                </div>

                <a
                  href={apiClient.getExportSeatmapUrl(eventId)}
                  className="flex items-center gap-2 px-3 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
                >
                  <Download size={16} />
                  导出
                </a>
              </>
            )}
          </div>

          {/* Zone paint palette (visible when paint mode active) */}
          {paintMode && showZonePanel && (
            <div className="mt-4 p-3 bg-indigo-50 rounded-lg border border-indigo-200">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-medium text-indigo-900">选择分区颜色，点击座位涂色：</span>
                <button
                  onClick={() => { setPaintMode(false); setShowZonePanel(false); }}
                  className="ml-auto p-1 hover:bg-indigo-100 rounded"
                >
                  <X size={16} className="text-indigo-600" />
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {ZONE_PALETTE.map((z) => (
                  <button
                    key={z.name}
                    onClick={() => setPaintZone(z.name)}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border-2 transition-all ${
                      paintZone === z.name
                        ? 'ring-2 ring-offset-1 ring-indigo-500 scale-105'
                        : ''
                    }`}
                    style={{
                      backgroundColor: `${z.color}22`,
                      borderColor: z.color,
                      color: z.color,
                    }}
                  >
                    <span
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: z.color }}
                    />
                    {z.name}
                  </button>
                ))}
                {/* Clear zone option */}
                <button
                  onClick={() => setPaintZone('')}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border-2 border-gray-300 text-gray-500 ${
                    paintZone === '' ? 'ring-2 ring-offset-1 ring-indigo-500' : ''
                  }`}
                >
                  <span className="w-3 h-3 rounded-full bg-gray-300" />
                  清除分区
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Seat Map Visualization */}
        <div className="bg-white rounded-lg shadow p-6">
          {seatsLoading ? (
            <div className="text-center text-gray-500 py-8">加载中...</div>
          ) : !hasSeats ? (
            <div className="text-center py-12">
              <Grid3X3 size={48} className="mx-auto text-gray-300 mb-4" />
              <p className="text-gray-500 mb-2">
                {rows > 0 && cols > 0
                  ? '还没有生成座位，点击上方"生成座位"按钮'
                  : '请先在设置中配置会场行列数'}
              </p>
            </div>
          ) : (
            renderSeatGrid()
          )}
        </div>

        {/* Selected Seat Detail */}
        {selectedSeat && (
          <div className="bg-white rounded-lg shadow p-6">
            <h4 className="text-sm font-semibold text-gray-900 mb-3">座位详情</h4>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
              <div>
                <span className="text-gray-500">座位号：</span>
                <span className="font-medium">{selectedSeat.label}</span>
              </div>
              <div>
                <span className="text-gray-500">位置：</span>
                <span className="font-medium">
                  第 {selectedSeat.row_num} 排，第 {selectedSeat.col_num} 列
                </span>
              </div>
              <div>
                <span className="text-gray-500">类型：</span>
                <span className="font-medium">{selectedSeat.seat_type}</span>
              </div>
              <div>
                <span className="text-gray-500">分区：</span>
                <span className="font-medium">{selectedSeat.zone || '无'}</span>
              </div>
              <div>
                <span className="text-gray-500">入座人：</span>
                <span className="font-medium">
                  {selectedSeat.attendee_id
                    ? (() => {
                        const att = attendeeMap.get(selectedSeat.attendee_id);
                        return att ? `${att.name} (${att.role}, P${att.priority})` : '未知';
                      })()
                    : '空座'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Feedback messages */}
        {autoAssignMutation.isSuccess && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
            自动排座完成，共分配 {(autoAssignMutation.data as any)?.count || 0} 个座位
          </div>
        )}
        {autoAssignMutation.isError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-800">
            排座失败：{(autoAssignMutation.error as Error)?.message}
          </div>
        )}
        {suggestZonesMutation.isSuccess && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
            AI 智能分区已应用！分区基于参会人优先级分布自动规划。
          </div>
        )}
      </div>

      {/* AI Agent Sidebar (toggle) */}
      {showAgent && (
        <div className="w-80 flex-shrink-0">
          <SubAgentPanel
            eventId={eventId}
            scope="seating"
            title="排座 AI 助手"
            placeholder="例如：把高优先级的嘉宾安排到前排..."
            welcomeMessage="我可以帮你规划座位分区、调整排座策略，或回答关于座位安排的问题。"
          />
        </div>
      )}

      {/* Floating AI toggle */}
      <button
        onClick={() => setShowAgent(!showAgent)}
        className={`fixed bottom-6 right-6 p-3 rounded-full shadow-lg transition-colors z-30 ${
          showAgent
            ? 'bg-indigo-600 text-white'
            : 'bg-white text-indigo-600 border border-indigo-200 hover:bg-indigo-50'
        }`}
        title="排座 AI 助手"
      >
        <Sparkles size={20} />
      </button>
    </div>
  );
}
