import { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Grid3X3, Shuffle, Users, Download, Sparkles,
  Paintbrush, X, ZoomIn, ZoomOut, Move, MousePointer,
  UserPlus, XCircle,
} from 'lucide-react';
import { apiClient } from '../../lib/api';
import { SubAgentPanel } from '../SubAgentPanel';

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

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
  pos_x: number | null;
  pos_y: number | null;
  rotation: number | null;
}

interface Attendee {
  id: string;
  name: string;
  role: string;
  priority: number;
  department: string | null;
  status: string;
}

interface ZoneSuggestion {
  zone: string;
  min_priority: number;
  rows: number[];
  color: string;
  description: string;
}

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

const LAYOUT_OPTIONS: { value: string; label: string; desc: string }[] = [
  { value: 'grid', label: '方形网格', desc: '标准长方形网格' },
  { value: 'theater', label: '剧院弧形', desc: '弧形排列，面向讲台' },
  { value: 'classroom', label: '课桌式', desc: '双人课桌排列' },
  { value: 'roundtable', label: '圆桌式', desc: '多桌圆形座位' },
  { value: 'banquet', label: '宴会长桌', desc: '长桌两侧座位' },
  { value: 'u_shape', label: 'U 形', desc: '三面围合，适合会议' },
];

const ZONE_PALETTE = [
  { name: '贵宾区', color: '#e2b93b' },
  { name: '嘉宾区', color: '#4a90d9' },
  { name: '媒体区', color: '#9b59b6' },
  { name: '工作人员区', color: '#27ae60' },
  { name: '普通区', color: '#6b7280' },
];

const SEAT_RADIUS = 18;
const MIN_ZOOM = 0.3;
const MAX_ZOOM = 3;
// Zoom factor per wheel "step" (120 deltaY = 1 "notch" on most mice)
const ZOOM_STEP = 0.06;

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function getSeatFill(
  seat: Seat,
  att: Attendee | undefined,
  zoneColorMap: Map<string, string>,
): string {
  if (seat.seat_type === 'disabled') return '#d1d5db';
  if (seat.seat_type === 'aisle') return 'transparent';
  if (seat.attendee_id && att) {
    if (att.priority >= 10) return '#c4b5fd';
    if (att.priority >= 5) return '#fde68a';
    return '#bbf7d0';
  }
  if (seat.seat_type === 'reserved') {
    const zc = seat.zone ? zoneColorMap.get(seat.zone) : undefined;
    return zc ? `${zc}55` : '#fef3c7';
  }
  if (seat.zone) {
    const zc = zoneColorMap.get(seat.zone);
    return zc ? `${zc}33` : '#dbeafe';
  }
  return '#dbeafe';
}

function getSeatStroke(
  seat: Seat,
  att: Attendee | undefined,
  zoneColorMap: Map<string, string>,
): string {
  if (seat.seat_type === 'disabled') return '#9ca3af';
  if (seat.seat_type === 'aisle') return 'transparent';
  if (seat.attendee_id && att) {
    if (att.priority >= 10) return '#7c3aed';
    if (att.priority >= 5) return '#d97706';
    return '#22c55e';
  }
  if (seat.zone) {
    const zc = zoneColorMap.get(seat.zone);
    return zc || '#93c5fd';
  }
  return '#93c5fd';
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function SeatingTab({ eventId, event }: SeatingTabProps) {
  // ── state ──
  const [selectedSeat, setSelectedSeat] = useState<Seat | null>(null);
  const [strategy, setStrategy] = useState('priority_first');
  const [paintMode, setPaintMode] = useState(false);
  const [paintZone, setPaintZone] = useState<string>('贵宾区');
  const [showAgent, setShowAgent] = useState(false);
  const [showZonePanel, setShowZonePanel] = useState(false);
  const [layoutType, setLayoutType] = useState(event.layout_type || 'grid');
  const [tableSize, setTableSize] = useState(8);
  // Assign picker
  const [showAssignPicker, setShowAssignPicker] = useState(false);
  const [assignSearch, setAssignSearch] = useState('');

  // SVG pan/zoom
  const zoomRef = useRef(1);
  const [zoom, _setZoom] = useState(1);
  const setZoom = useCallback((v: number | ((z: number) => number)) => {
    _setZoom((prev) => {
      const next = typeof v === 'function' ? v(prev) : v;
      const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(next * 100) / 100));
      zoomRef.current = clamped;
      return clamped;
    });
  }, []);
  const panRef = useRef({ x: 40, y: 60 });
  const [pan, _setPan] = useState({ x: 40, y: 60 });
  const setPan = useCallback((v: { x: number; y: number }) => {
    panRef.current = v;
    _setPan(v);
  }, []);
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0, px: 0, py: 0 });

  // Drag selection
  const [selRect, setSelRect] = useState<{
    x: number; y: number; w: number; h: number;
  } | null>(null);
  const selStart = useRef<{ x: number; y: number } | null>(null);
  // Track selected seat IDs from drag-select (non-paint mode)
  const [dragSelectedIds, setDragSelectedIds] = useState<Set<string>>(new Set());

  // Tool mode: 'select' | 'pan'
  const [toolMode, setToolMode] = useState<'select' | 'pan'>('select');

  const svgRef = useRef<SVGSVGElement>(null);
  const queryClient = useQueryClient();

  // ── data fetching ──
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

  // ── mutations ──
  const createLayoutMutation = useMutation({
    mutationFn: () =>
      apiClient.createSeatLayout(eventId, {
        layout_type: layoutType,
        rows: event.venue_rows,
        cols: event.venue_cols,
        table_size: tableSize,
      }),
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

  const bulkUpdateMutation = useMutation({
    mutationFn: (params: { seat_ids: string[]; zone?: string | null }) =>
      apiClient.bulkUpdateSeats(eventId, params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
    },
  });

  const assignSeatMutation = useMutation({
    mutationFn: (params: { seatId: string; attendeeId: string }) =>
      apiClient.assignSeat(eventId, params.seatId, params.attendeeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', eventId] });
      setShowAssignPicker(false);
      setAssignSearch('');
    },
  });

  const unassignSeatMutation = useMutation({
    mutationFn: (seatId: string) =>
      apiClient.updateSeat(eventId, seatId, { attendee_id: null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard', eventId] });
    },
  });

  const suggestZonesMutation = useMutation({
    mutationFn: () => apiClient.suggestZones(eventId),
    onSuccess: async (data: any) => {
      const zones = data.zones as ZoneSuggestion[];
      for (const zone of zones) {
        const ids = (seats as Seat[])
          .filter((s) => zone.rows.includes(s.row_num))
          .map((s) => s.id);
        if (ids.length > 0) {
          await apiClient.bulkUpdateSeats(eventId, {
            seat_ids: ids,
            zone: zone.zone,
          });
        }
      }
      queryClient.invalidateQueries({ queryKey: ['seats', eventId] });
    },
  });

  // ── lookups ──
  const attendeeMap = useMemo(() => {
    const map = new Map<string, Attendee>();
    (attendees as Attendee[]).forEach((a) => map.set(a.id, a));
    return map;
  }, [attendees]);

  const zoneColorMap = useMemo(() => {
    const map = new Map<string, string>();
    const uniqueZones = new Set<string>();
    (seats as Seat[]).forEach((s) => {
      if (s.zone) uniqueZones.add(s.zone);
    });
    Array.from(uniqueZones).forEach((z, i) => {
      const preset = ZONE_PALETTE.find((p) => p.name === z);
      map.set(z, preset?.color || ZONE_PALETTE[i % ZONE_PALETTE.length].color);
    });
    return map;
  }, [seats]);

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

  // ── derived values ──
  const hasSeats = (seats as Seat[]).length > 0;
  const assignedCount = (seats as Seat[]).filter((s) => s.attendee_id).length;
  const totalSeats = (seats as Seat[]).length;
  // Attendees already seated
  const seatedIds = useMemo(() => {
    const set = new Set<string>();
    (seats as Seat[]).forEach((s) => {
      if (s.attendee_id) set.add(s.attendee_id);
    });
    return set;
  }, [seats]);
  const unassignedAttendees = useMemo(() =>
    (attendees as Attendee[]).filter(
      (a) => a.status !== 'cancelled' && !seatedIds.has(a.id),
    ),
  [attendees, seatedIds]);
  const totalAttendees = (attendees as Attendee[]).filter(
    (a) => a.status !== 'cancelled',
  ).length;

  // Filtered attendee list for assign picker
  const filteredUnassigned = useMemo(() => {
    if (!assignSearch.trim()) return unassignedAttendees.slice(0, 20);
    const q = assignSearch.toLowerCase();
    return unassignedAttendees
      .filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          (a.role || '').toLowerCase().includes(q) ||
          (a.department || '').toLowerCase().includes(q),
      )
      .slice(0, 20);
  }, [unassignedAttendees, assignSearch]);

  // Compute SVG viewBox from seat positions
  const bounds = useMemo(() => {
    const typed = seats as Seat[];
    if (typed.length === 0) return { minX: 0, minY: 0, maxX: 600, maxY: 400 };
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const s of typed) {
      const x = s.pos_x ?? (s.col_num - 1) * 60;
      const y = s.pos_y ?? (s.row_num - 1) * 60;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
    return {
      minX: minX - 40,
      minY: minY - 60,
      maxX: maxX + 40,
      maxY: maxY + 40,
    };
  }, [seats]);

  // ── SVG coordinate helpers ──
  // Use refs so native event handlers always see the latest zoom/pan
  const svgPoint = useCallback(
    (clientX: number, clientY: number) => {
      if (!svgRef.current) return { x: 0, y: 0 };
      const rect = svgRef.current.getBoundingClientRect();
      const z = zoomRef.current;
      const p = panRef.current;
      const x = (clientX - rect.left) / z - p.x;
      const y = (clientY - rect.top) / z - p.y;
      return { x, y };
    },
    [],
  );

  // Refs for values used in document-level listeners (avoids stale closures)
  const isPanningRef = useRef(false);
  const toolModeRef = useRef(toolMode);
  const paintModeRef = useRef(paintMode);
  const paintZoneRef = useRef(paintZone);
  const seatsRef = useRef(seats);
  const selRectRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  useEffect(() => { toolModeRef.current = toolMode; }, [toolMode]);
  useEffect(() => { paintModeRef.current = paintMode; }, [paintMode]);
  useEffect(() => { paintZoneRef.current = paintZone; }, [paintZone]);
  useEffect(() => { seatsRef.current = seats; }, [seats]);
  // Stable ref for mutate so document listeners don't depend on mutation object
  const bulkMutateRef = useRef(bulkUpdateMutation.mutate);
  useEffect(() => { bulkMutateRef.current = bulkUpdateMutation.mutate; }, [bulkUpdateMutation.mutate]);

  // Helper: find seats in a selection rect
  const findSeatsInRect = useCallback(
    (rect: { x: number; y: number; w: number; h: number }) => {
      return (seatsRef.current as Seat[]).filter((s) => {
        if (s.seat_type === 'disabled' || s.seat_type === 'aisle') return false;
        const sx = s.pos_x ?? (s.col_num - 1) * 60;
        const sy = s.pos_y ?? (s.row_num - 1) * 60;
        return (
          sx >= rect.x &&
          sx <= rect.x + rect.w &&
          sy >= rect.y &&
          sy <= rect.y + rect.h
        );
      });
    },
    [],
  );

  // ── pan / drag handlers (document-level for reliability) ──
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      // Middle / right click → always pan
      if (e.button === 1 || e.button === 2) {
        e.preventDefault();
        isPanningRef.current = true;
        setIsPanning(true);
        panStart.current = {
          x: e.clientX, y: e.clientY,
          px: panRef.current.x, py: panRef.current.y,
        };
        return;
      }
      if (toolModeRef.current === 'pan') {
        isPanningRef.current = true;
        setIsPanning(true);
        panStart.current = {
          x: e.clientX, y: e.clientY,
          px: panRef.current.x, py: panRef.current.y,
        };
        return;
      }
      // Select / paint mode → start drag selection
      if (paintModeRef.current || toolModeRef.current === 'select') {
        const pt = svgPoint(e.clientX, e.clientY);
        selStart.current = pt;
        const initRect = { x: pt.x, y: pt.y, w: 0, h: 0 };
        selRectRef.current = initRect;
        setSelRect(initRect);
        setDragSelectedIds(new Set());
      }
    },
    [svgPoint],
  );

  // Document-level move / up so drag continues outside SVG.
  // All state is read via refs — zero dependency on React state objects,
  // so this effect registers listeners exactly once.
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (isPanningRef.current) {
        const z = zoomRef.current;
        const dx = (e.clientX - panStart.current.x) / z;
        const dy = (e.clientY - panStart.current.y) / z;
        setPan({ x: panStart.current.px + dx, y: panStart.current.py + dy });
        return;
      }
      if (selStart.current) {
        const pt = svgPoint(e.clientX, e.clientY);
        const sx = selStart.current.x;
        const sy = selStart.current.y;
        const newRect = {
          x: Math.min(sx, pt.x),
          y: Math.min(sy, pt.y),
          w: Math.abs(pt.x - sx),
          h: Math.abs(pt.y - sy),
        };
        selRectRef.current = newRect;
        setSelRect(newRect);
        // Live preview: highlight seats inside rect
        if (newRect.w > 2 || newRect.h > 2) {
          const found = findSeatsInRect(newRect);
          setDragSelectedIds(new Set(found.map((s) => s.id)));
        }
      }
    };

    const onUp = () => {
      if (isPanningRef.current) {
        isPanningRef.current = false;
        setIsPanning(false);
        return;
      }
      if (selStart.current) {
        // Read final rect from ref (not from React state — avoids stale closure)
        const finalRect = selRectRef.current;
        if (finalRect && (finalRect.w > 3 || finalRect.h > 3)) {
          const selected = findSeatsInRect(finalRect);
          if (selected.length > 0) {
            if (paintModeRef.current) {
              // Paint mode: apply zone to selected seats
              bulkMutateRef.current({
                seat_ids: selected.map((s) => s.id),
                zone: paintZoneRef.current || null,
              });
              setDragSelectedIds(new Set());
            } else {
              // Select mode: keep highlighted so user can pick a zone
              setDragSelectedIds(new Set(selected.map((s) => s.id)));
            }
          }
        }
        // Clean up
        selStart.current = null;
        selRectRef.current = null;
        setSelRect(null);
      }
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
  }, [svgPoint, setPan, findSeatsInRect]);

  // ── Zoom: native wheel listener (non-passive) + zoom toward cursor ──
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const rect = svg.getBoundingClientRect();
      // Mouse position in screen coords relative to SVG element
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      // Normalize: mice send ±120 per notch, trackpads send smaller values
      const normalized =
        Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY) / 120, 1);
      const factor = 1 - normalized * ZOOM_STEP;

      const oldZ = zoomRef.current;
      const newZ = Math.max(
        MIN_ZOOM,
        Math.min(MAX_ZOOM, Math.round(oldZ * factor * 100) / 100),
      );
      if (newZ === oldZ) return;

      // Zoom toward cursor: adjust pan so the point under the cursor stays fixed
      // Before: screenPt = (svgPt + pan) * oldZ => svgPt = screenPt/oldZ - pan
      // After:  (svgPt + newPan) * newZ = screenPt
      //   => newPan = screenPt / newZ - svgPt = screenPt / newZ - (screenPt / oldZ - pan)
      const p = panRef.current;
      const newPanX = mx / newZ - (mx / oldZ - p.x);
      const newPanY = my / newZ - (my / oldZ - p.y);

      // Batch updates
      zoomRef.current = newZ;
      panRef.current = { x: newPanX, y: newPanY };
      _setZoom(newZ);
      _setPan({ x: newPanX, y: newPanY });
    };
    const prevent = (e: Event) => e.preventDefault();
    svg.addEventListener('wheel', onWheel, { passive: false });
    svg.addEventListener('contextmenu', prevent);
    return () => {
      svg.removeEventListener('wheel', onWheel);
      svg.removeEventListener('contextmenu', prevent);
    };
  }, []);

  // ── seat click ──
  const handleSeatClick = (seat: Seat, e: React.MouseEvent) => {
    e.stopPropagation();
    if (seat.seat_type === 'disabled' || seat.seat_type === 'aisle') return;
    if (paintMode) {
      bulkUpdateMutation.mutate({
        seat_ids: [seat.id],
        zone: paintZone || null,
      });
      return;
    }
    // Clear drag selection on single click
    setDragSelectedIds(new Set());
    if (selectedSeat?.id === seat.id) {
      setSelectedSeat(null);
      setShowAssignPicker(false);
    } else {
      setSelectedSeat(seat);
      setShowAssignPicker(false);
    }
  };

  // ── render SVG ──
  const renderSVGCanvas = () => {
    if (!hasSeats) return null;

    const width = bounds.maxX - bounds.minX + 80;
    const height = bounds.maxY - bounds.minY + 80;

    return (
      <svg
        ref={svgRef}
        className="w-full border border-gray-200 rounded-lg bg-gray-50"
        style={{
          height: Math.min(600, Math.max(350, height * zoom + 80)),
          cursor: isPanning
            ? 'grabbing'
            : toolMode === 'pan'
              ? 'grab'
              : paintMode
                ? 'crosshair'
                : 'default',
        }}
        onMouseDown={handleMouseDown}
      >
        <g transform={`scale(${zoom}) translate(${pan.x}, ${pan.y})`}>
          {/* Stage bar */}
          <rect
            x={bounds.minX}
            y={bounds.minY - 10}
            width={bounds.maxX - bounds.minX}
            height={24}
            rx={4}
            fill="#1f2937"
          />
          <text
            x={(bounds.minX + bounds.maxX) / 2}
            y={bounds.minY + 6}
            textAnchor="middle"
            fill="white"
            fontSize={11}
            fontWeight="500"
          >
            讲台 / 前方
          </text>

          {/* Seats */}
          {(seats as Seat[]).map((seat) => {
            const x = seat.pos_x ?? (seat.col_num - 1) * 60;
            const y = seat.pos_y ?? (seat.row_num - 1) * 60;
            if (seat.seat_type === 'aisle') return null;
            const att = seat.attendee_id
              ? attendeeMap.get(seat.attendee_id)
              : undefined;
            const fill = getSeatFill(seat, att, zoneColorMap);
            const stroke = getSeatStroke(seat, att, zoneColorMap);
            const isSelected = selectedSeat?.id === seat.id;
            const isDragSelected = dragSelectedIds.has(seat.id);
            const rotation = seat.rotation || 0;
            const displayLabel = seat.attendee_id
              ? (att?.name?.slice(0, 2) || '✓')
              : (seat.label || '');

            return (
              <g
                key={seat.id}
                transform={`translate(${x}, ${y}) rotate(${rotation})`}
                onClick={(e) => handleSeatClick(seat, e)}
                style={{ cursor: paintMode ? 'crosshair' : 'pointer' }}
              >
                <circle
                  r={SEAT_RADIUS}
                  fill={isDragSelected ? '#e0e7ff' : fill}
                  stroke={
                    isSelected ? '#4f46e5'
                    : isDragSelected ? '#6366f1'
                    : stroke
                  }
                  strokeWidth={isSelected ? 3 : isDragSelected ? 2.5 : 1.5}
                />
                {(isSelected || isDragSelected) && (
                  <circle
                    r={SEAT_RADIUS + 4}
                    fill="none"
                    stroke={isSelected ? '#4f46e5' : '#818cf8'}
                    strokeWidth={1.5}
                    strokeDasharray="4,3"
                  />
                )}
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={10}
                  fontWeight="500"
                  fill="#374151"
                  transform={`rotate(${-rotation})`}
                  style={{ pointerEvents: 'none', userSelect: 'none' }}
                >
                  {displayLabel.length > 3
                    ? displayLabel.slice(0, 3)
                    : displayLabel}
                </text>
                <title>
                  {seat.label}
                  {seat.zone ? ` [${seat.zone}]` : ''}
                  {att ? ` - ${att.name} (P${att.priority})` : ''}
                </title>
              </g>
            );
          })}

          {/* Drag selection rectangle */}
          {selRect && selRect.w > 2 && (
            <rect
              x={selRect.x}
              y={selRect.y}
              width={selRect.w}
              height={selRect.h}
              fill="rgba(79,70,229,0.12)"
              stroke="#4f46e5"
              strokeWidth={1}
              strokeDasharray="6,3"
              pointerEvents="none"
            />
          )}
        </g>
      </svg>
    );
  };

  // ── Selected seat detail panel with assign/unassign ──
  const renderSeatDetail = () => {
    if (!selectedSeat) return null;
    const att = selectedSeat.attendee_id
      ? attendeeMap.get(selectedSeat.attendee_id)
      : undefined;

    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold text-gray-900">
            座位详情 — {selectedSeat.label}
          </h4>
          <button
            onClick={() => { setSelectedSeat(null); setShowAssignPicker(false); }}
            className="p-1 hover:bg-gray-100 rounded"
          >
            <X size={14} className="text-gray-400" />
          </button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
          <div>
            <span className="text-gray-500">坐标：</span>
            <span className="font-medium">
              ({Math.round(selectedSeat.pos_x ?? 0)},{' '}
              {Math.round(selectedSeat.pos_y ?? 0)})
            </span>
          </div>
          <div>
            <span className="text-gray-500">类型：</span>
            <span className="font-medium">{selectedSeat.seat_type}</span>
          </div>
          <div>
            <span className="text-gray-500">分区：</span>
            <span className="font-medium">
              {selectedSeat.zone || '无'}
            </span>
          </div>
          <div>
            <span className="text-gray-500">入座人：</span>
            <span className="font-medium">
              {att
                ? `${att.name} (${att.role}, P${att.priority})`
                : '空座'}
            </span>
          </div>
        </div>

        {/* Assign / Unassign actions */}
        <div className="border-t pt-3">
          {selectedSeat.attendee_id && att ? (
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">
                当前入座：<strong>{att.name}</strong>
              </span>
              <button
                onClick={() => unassignSeatMutation.mutate(selectedSeat.id)}
                disabled={unassignSeatMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 text-red-600 border border-red-200 rounded-lg text-xs hover:bg-red-50 disabled:opacity-50"
              >
                <XCircle size={14} />
                取消分配
              </button>
            </div>
          ) : (
            <div>
              {!showAssignPicker ? (
                <button
                  onClick={() => setShowAssignPicker(true)}
                  disabled={unassignedAttendees.length === 0}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs hover:bg-indigo-700 disabled:opacity-50"
                >
                  <UserPlus size={14} />
                  {unassignedAttendees.length === 0
                    ? '没有待分配的参会者'
                    : '指定入座人'}
                </button>
              ) : (
                <div className="space-y-2">
                  <input
                    type="text"
                    value={assignSearch}
                    onChange={(e) => setAssignSearch(e.target.value)}
                    placeholder="搜索姓名、角色、部门..."
                    className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    autoFocus
                  />
                  <div className="max-h-40 overflow-y-auto border border-gray-200 rounded-lg divide-y">
                    {filteredUnassigned.length === 0 ? (
                      <div className="px-3 py-2 text-xs text-gray-400">
                        无匹配结果
                      </div>
                    ) : (
                      filteredUnassigned.map((a) => (
                        <button
                          key={a.id}
                          onClick={() =>
                            assignSeatMutation.mutate({
                              seatId: selectedSeat.id,
                              attendeeId: a.id,
                            })
                          }
                          disabled={assignSeatMutation.isPending}
                          className="w-full flex items-center justify-between px-3 py-2 hover:bg-indigo-50 transition-colors disabled:opacity-50"
                        >
                          <div className="text-left">
                            <span className="text-xs font-medium text-gray-900">
                              {a.name}
                            </span>
                            <span className="text-[10px] text-gray-500 ml-2">
                              {a.role} · P{a.priority}
                              {a.department ? ` · ${a.department}` : ''}
                            </span>
                          </div>
                          <UserPlus size={12} className="text-indigo-400" />
                        </button>
                      ))
                    )}
                  </div>
                  <button
                    onClick={() => { setShowAssignPicker(false); setAssignSearch(''); }}
                    className="text-xs text-gray-500 hover:text-gray-700"
                  >
                    取消
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex gap-6">
      {/* Main content */}
      <div className="flex-1 space-y-6">
        {/* Header + Actions */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900">
                座位布局
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                {event.venue_rows} 排 × {event.venue_cols} 列 ·
                支持自由布局和异形会场
              </p>
            </div>

            {/* Legend */}
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <span className="flex items-center gap-1">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: '#bbf7d0', border: '1px solid #22c55e' }}
                />
                已分配
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: '#c4b5fd', border: '1px solid #7c3aed' }}
                />
                高优先
              </span>
              <span className="flex items-center gap-1">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: '#dbeafe', border: '1px solid #93c5fd' }}
                />
                空座
              </span>
              {activeZones.map((z) => (
                <span key={z.name} className="flex items-center gap-1">
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{
                      backgroundColor: `${z.color}33`,
                      border: `1px solid ${z.color}`,
                    }}
                  />
                  {z.name} ({z.count})
                </span>
              ))}
            </div>
          </div>

          {/* Layout selector + Generate */}
          <div className="flex flex-wrap gap-3 items-center mb-4">
            <select
              value={layoutType}
              onChange={(e) => setLayoutType(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {LAYOUT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label} — {opt.desc}
                </option>
              ))}
            </select>

            {(layoutType === 'roundtable' || layoutType === 'banquet') && (
              <div className="flex items-center gap-1.5 text-sm">
                <label className="text-gray-600">每桌:</label>
                <input
                  type="number"
                  min={4}
                  max={16}
                  value={tableSize}
                  onChange={(e) => setTableSize(Number(e.target.value))}
                  className="w-16 px-2 py-1.5 border border-gray-300 rounded text-center"
                />
                <span className="text-gray-400">人</span>
              </div>
            )}

            <button
              onClick={() => createLayoutMutation.mutate()}
              disabled={
                createLayoutMutation.isPending ||
                event.venue_rows === 0 ||
                event.venue_cols === 0
              }
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium disabled:opacity-50"
            >
              <Grid3X3 size={18} />
              {createLayoutMutation.isPending
                ? '生成中...'
                : hasSeats
                  ? '重新生成'
                  : '生成座位'}
            </button>

            {/* Zoom & pan tools */}
            {hasSeats && (
              <div className="flex items-center gap-1 border-l pl-3 ml-1">
                <button
                  onClick={() => setToolMode('select')}
                  className={`p-1.5 rounded ${
                    toolMode === 'select'
                      ? 'bg-indigo-100 text-indigo-700'
                      : 'text-gray-500 hover:bg-gray-100'
                  }`}
                  title="选择 / 框选"
                >
                  <MousePointer size={16} />
                </button>
                <button
                  onClick={() => setToolMode('pan')}
                  className={`p-1.5 rounded ${
                    toolMode === 'pan'
                      ? 'bg-indigo-100 text-indigo-700'
                      : 'text-gray-500 hover:bg-gray-100'
                  }`}
                  title="拖拽平移"
                >
                  <Move size={16} />
                </button>
                <button
                  onClick={() =>
                    setZoom((z) => Math.min(MAX_ZOOM, z * 1.25))
                  }
                  className="p-1.5 rounded text-gray-500 hover:bg-gray-100"
                  title="放大"
                >
                  <ZoomIn size={16} />
                </button>
                <button
                  onClick={() =>
                    setZoom((z) => Math.max(MIN_ZOOM, z * 0.8))
                  }
                  className="p-1.5 rounded text-gray-500 hover:bg-gray-100"
                  title="缩小"
                >
                  <ZoomOut size={16} />
                </button>
                <span className="text-xs text-gray-400 ml-1">
                  {Math.round(zoom * 100)}%
                </span>
              </div>
            )}
          </div>

          {/* Assignment + zone tools */}
          {hasSeats && (
            <div className="flex flex-wrap gap-3 items-center">
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
                  disabled={
                    autoAssignMutation.isPending ||
                    unassignedAttendees.length === 0
                  }
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-medium disabled:opacity-50"
                >
                  <Shuffle size={18} />
                  {autoAssignMutation.isPending ? '分配中...' : '自动排座'}
                </button>
              </div>

              <div className="flex items-center gap-2 border-l pl-3 ml-1">
                <button
                  onClick={() => suggestZonesMutation.mutate()}
                  disabled={suggestZonesMutation.isPending}
                  className="flex items-center gap-2 px-3 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors text-sm font-medium disabled:opacity-50"
                  title="根据参会人优先级自动规划分区"
                >
                  <Sparkles size={16} />
                  {suggestZonesMutation.isPending
                    ? 'AI分区中...'
                    : 'AI智能分区'}
                </button>
                <button
                  onClick={() => {
                    const next = !paintMode;
                    setPaintMode(next);
                    setShowZonePanel(next);
                    if (next) setToolMode('select');
                  }}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    paintMode
                      ? 'bg-indigo-600 text-white'
                      : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  <Paintbrush size={16} />
                  {paintMode ? '退出涂色' : '手动分区 (框选)'}
                </button>
              </div>

              <div className="flex items-center gap-1 text-sm text-gray-500 ml-auto">
                <Users size={16} />
                已分配 {assignedCount}/{totalSeats}
                {totalAttendees > 0 && (
                  <> · 待分配 {unassignedAttendees.length}/{totalAttendees} 人</>
                )}
              </div>

              <a
                href={apiClient.getExportSeatmapUrl(eventId)}
                className="flex items-center gap-2 px-3 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
              >
                <Download size={16} />
                导出
              </a>
            </div>
          )}

          {/* Zone paint palette */}
          {paintMode && showZonePanel && (
            <div className="mt-4 p-3 bg-indigo-50 rounded-lg border border-indigo-200">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-sm font-medium text-indigo-900">
                  选择分区，然后在座位图上拖拽框选批量涂色：
                </span>
                <button
                  onClick={() => {
                    setPaintMode(false);
                    setShowZonePanel(false);
                  }}
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
                <button
                  onClick={() => setPaintZone('')}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium border-2 border-gray-300 text-gray-500 ${
                    paintZone === ''
                      ? 'ring-2 ring-offset-1 ring-indigo-500'
                      : ''
                  }`}
                >
                  <span className="w-3 h-3 rounded-full bg-gray-300" />
                  清除分区
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Drag-select action bar (non-paint mode) */}
        {dragSelectedIds.size > 0 && !paintMode && (
          <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 flex items-center gap-3 flex-wrap">
            <span className="text-sm font-medium text-indigo-900">
              已框选 {dragSelectedIds.size} 个座位
            </span>
            <div className="flex items-center gap-2">
              {ZONE_PALETTE.map((z) => (
                <button
                  key={z.name}
                  onClick={() => {
                    bulkUpdateMutation.mutate({
                      seat_ids: Array.from(dragSelectedIds),
                      zone: z.name,
                    });
                    setDragSelectedIds(new Set());
                  }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium border transition-colors hover:opacity-80"
                  style={{
                    backgroundColor: `${z.color}22`,
                    borderColor: z.color,
                    color: z.color,
                  }}
                >
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: z.color }}
                  />
                  {z.name}
                </button>
              ))}
              <button
                onClick={() => {
                  bulkUpdateMutation.mutate({
                    seat_ids: Array.from(dragSelectedIds),
                    zone: null,
                  });
                  setDragSelectedIds(new Set());
                }}
                className="px-2 py-1 rounded text-xs font-medium border border-gray-300 text-gray-500 hover:bg-gray-100"
              >
                清除分区
              </button>
            </div>
            <button
              onClick={() => setDragSelectedIds(new Set())}
              className="ml-auto text-xs text-indigo-600 hover:text-indigo-800"
            >
              取消选择
            </button>
          </div>
        )}

        {/* SVG Canvas */}
        <div className="bg-white rounded-lg shadow p-4">
          {seatsLoading ? (
            <div className="text-center text-gray-500 py-8">加载中...</div>
          ) : !hasSeats ? (
            <div className="text-center py-12">
              <Grid3X3 size={48} className="mx-auto text-gray-300 mb-4" />
              <p className="text-gray-500 mb-2">
                {event.venue_rows > 0 && event.venue_cols > 0
                  ? '选择布局类型，点击"生成座位"'
                  : '请先在设置中配置会场行列数'}
              </p>
            </div>
          ) : (
            renderSVGCanvas()
          )}
        </div>

        {/* Selected Seat Detail with assign/unassign */}
        {renderSeatDetail()}

        {/* Feedback messages */}
        {autoAssignMutation.isSuccess && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
            自动排座完成，共分配{' '}
            {(autoAssignMutation.data as any)?.count || 0} 个座位
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
        {createLayoutMutation.isSuccess && (
          <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 text-sm text-indigo-800">
            布局已生成！共创建 {totalSeats} 个座位。
          </div>
        )}
      </div>

      {/* AI Agent Sidebar */}
      {showAgent && (
        <div className="w-80 flex-shrink-0">
          <SubAgentPanel
            eventId={eventId}
            scope="seating"
            title="排座 AI 助手"
            placeholder="例如：帮我用圆桌布局重新排座..."
            welcomeMessage="我可以帮你：
1. 生成布局 — 如「用剧院弧形生成座位」
2. 自动排座 — 如「按优先级排座」
3. 分区规划 — 如「前3排设为贵宾区」
4. 查看状态 — 如「目前排座情况」"
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
