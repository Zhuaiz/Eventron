/**
 * BadgeTab — Badge/nameplate management inside an event.
 * Template previews use scaled iframes (no scrollbars).
 */
import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Tag, CreditCard, Download, Users, Plus, Eye,
  ChevronDown, ChevronRight, Trash2, Pencil, Award,
} from 'lucide-react';
import { apiClient } from '../../lib/api';
import { SubAgentPanel } from '../SubAgentPanel';
import { BadgeDesigner } from '../BadgeDesigner';

interface BadgeTabProps {
  eventId: string;
}

interface Attendee {
  id: string;
  name: string;
  title: string | null;
  organization: string | null;
  role: string;
  priority: number;
  status: string;
}

interface BadgeTemplate {
  id: string;
  name: string;
  template_type: string;
  style_category: string;
  is_builtin: boolean;
  html_template: string;
  css: string | null;
}

type BadgeTypeKey = 'conference' | 'badge' | 'tent_card';

/** Built-in template definitions with native pixel sizes for iframe scaling */
const BUILTIN_TYPES: {
  key: BadgeTypeKey;
  label: string;
  desc: string;
  templateName: string;
  icon: typeof Tag;
  color: string;
  activeColor: string;
  nativeW: number;
  nativeH: number;
}[] = [
  {
    key: 'conference',
    label: '竖版会议',
    desc: '90×130mm 深蓝',
    templateName: 'conference',
    icon: Award,
    color: 'text-blue-600',
    activeColor: 'bg-blue-600 text-white',
    nativeW: 340,
    nativeH: 492,
  },
  {
    key: 'badge',
    label: '横版胸牌',
    desc: '90×54mm 商务',
    templateName: 'business',
    icon: Tag,
    color: 'text-indigo-600',
    activeColor: 'bg-indigo-600 text-white',
    nativeW: 340,
    nativeH: 204,
  },
  {
    key: 'tent_card',
    label: '桌签',
    desc: '210×99mm 对折',
    templateName: 'tent_card',
    icon: CreditCard,
    color: 'text-green-600',
    activeColor: 'bg-green-600 text-white',
    nativeW: 794,
    nativeH: 375,
  },
];

/** Compute CSS scale to fit native size inside a box. */
function fitScale(nW: number, nH: number, boxW: number, boxH: number) {
  return Math.min(boxW / nW, boxH / nH);
}

/** Deterministic role color (same logic as badge_render.py) */
function roleColor(role: string): string {
  const colors = [
    '#e2b93b', '#e94560', '#0f9b58', '#4a90d9', '#9b59b6',
    '#00b894', '#fd79a8', '#636e72', '#0984e3', '#d63031',
  ];
  if (!role || role === '参会者') return '#6b7280';
  const h = [...role].reduce((sum, c) => sum + c.charCodeAt(0), 0);
  return colors[h % colors.length];
}

/* ───── Scaled iframe component (no scrollbar) ───── */

function ScaledIframe({
  src, nativeW, nativeH, boxW, boxH, title, onClick,
}: {
  src: string;
  nativeW: number;
  nativeH: number;
  boxW: number;
  boxH: number;
  title?: string;
  onClick?: () => void;
}) {
  const scale = fitScale(nativeW, nativeH, boxW, boxH);
  const thumbW = nativeW * scale;
  const thumbH = nativeH * scale;
  return (
    <div
      className={`flex justify-center items-center${onClick ? ' cursor-pointer' : ''}`}
      style={{ width: `${boxW}px`, height: `${boxH}px` }}
      onClick={onClick}
    >
      <div style={{
        width: `${thumbW}px`,
        height: `${thumbH}px`,
        overflow: 'hidden',
        borderRadius: '4px',
        boxShadow: '0 1px 6px rgba(0,0,0,0.12)',
      }}>
        <iframe
          src={src}
          scrolling="no"
          className="border-0 pointer-events-none"
          style={{
            width: `${nativeW}px`,
            height: `${nativeH}px`,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
          title={title || ''}
          tabIndex={-1}
        />
      </div>
    </div>
  );
}

export function BadgeTab({ eventId }: BadgeTabProps) {
  const queryClient = useQueryClient();
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [expandedRoles, setExpandedRoles] = useState<Set<string>>(new Set());
  const [badgeType, setBadgeType] = useState<BadgeTypeKey>('conference');
  const [designerOpen, setDesignerOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<BadgeTemplate | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // ── Data ──
  const { data: attendees = [] } = useQuery({
    queryKey: ['attendees', eventId],
    queryFn: async () => {
      const result = await apiClient.getAttendees(eventId);
      return ((result as any).data || result) as Attendee[];
    },
  });

  const { data: templates = [] } = useQuery({
    queryKey: ['badge-templates'],
    queryFn: () => apiClient.getBadgeTemplates() as Promise<BadgeTemplate[]>,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.deleteBadgeTemplate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['badge-templates'] });
      if (selectedTemplate) setSelectedTemplate(null);
    },
  });

  // Group attendees by role
  const roleGroups = useMemo(() => {
    const groups = new Map<string, Attendee[]>();
    const active = (attendees as Attendee[]).filter(
      (a) => a.status !== 'cancelled',
    );
    for (const a of active) {
      const role = a.role || '参会者';
      if (!groups.has(role)) groups.set(role, []);
      groups.get(role)!.push(a);
    }
    return Array.from(groups.entries())
      .sort(([, a], [, b]) => {
        const avgA = a.reduce((s, x) => s + x.priority, 0) / a.length;
        const avgB = b.reduce((s, x) => s + x.priority, 0) / b.length;
        return avgB - avgA;
      })
      .map(([role, members]) => ({ role, members, color: roleColor(role) }));
  }, [attendees]);

  const totalActive = roleGroups.reduce((s, g) => s + g.members.length, 0);

  // Custom templates (filter by type)
  const customTplType = badgeType === 'tent_card' ? 'tent_card' : 'badge';
  const customTemplates = (templates as BadgeTemplate[]).filter(
    (t) => !t.is_builtin && t.template_type === customTplType,
  );

  // Current builtin config
  const currentBuiltin = BUILTIN_TYPES.find((b) => b.key === badgeType)!;

  const toggleRole = (role: string) => {
    setExpandedRoles((prev) => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  };

  // ── Generate HTML for printing ──
  const handleGenerate = (
    templateName: string,
    templateId?: string,
    roles?: string[],
  ) => {
    const url = apiClient.getExportBadgesUrl(eventId, templateName, templateId, roles);
    window.open(url, '_blank');
  };

  const handleGenerateSelected = () => {
    if (selectedTemplate) {
      const tpl = (templates as BadgeTemplate[]).find(
        (t) => t.id === selectedTemplate,
      );
      handleGenerate(tpl?.template_type || currentBuiltin.templateName, selectedTemplate);
    } else {
      handleGenerate(currentBuiltin.templateName);
    }
  };

  // ── Preview template ──
  const handlePreview = (templateName: string, templateId?: string) => {
    const url = apiClient.getBadgePreviewUrl(eventId, templateName, templateId);
    setPreviewUrl(url);
  };

  const handlePreviewSelected = () => {
    if (selectedTemplate) {
      const tpl = (templates as BadgeTemplate[]).find(
        (t) => t.id === selectedTemplate,
      );
      handlePreview(tpl?.template_type || currentBuiltin.templateName, selectedTemplate);
    } else {
      handlePreview(currentBuiltin.templateName);
    }
  };

  // ── Designer save handler ──
  const handleDesignerSave = async (data: {
    html_template: string;
    css: string;
  }) => {
    if (editingTemplate) {
      await apiClient.updateBadgeTemplate(editingTemplate.id, {
        html_template: data.html_template,
        css: data.css,
      });
    } else {
      await apiClient.createBadgeTemplate({
        name: `自定义${currentBuiltin.label} ${new Date().toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`,
        template_type: customTplType,
        html_template: data.html_template,
        css: data.css,
        style_category: 'custom',
      });
    }
    queryClient.invalidateQueries({ queryKey: ['badge-templates'] });
    setDesignerOpen(false);
    setEditingTemplate(null);
  };

  // Preview iframe URL for built-in / selected template
  const mainPreviewUrl = selectedTemplate
    ? apiClient.getBadgePreviewUrl(eventId, currentBuiltin.templateName, selectedTemplate)
    : apiClient.getBadgePreviewUrl(eventId, currentBuiltin.templateName);

  // Main preview box sizes
  const MAIN_BOX_W = 240;
  const MAIN_BOX_H = 200;
  // Custom template thumbnail sizes
  const CUST_BOX_W = 120;
  const CUST_BOX_H = 90;

  return (
    <div className="flex h-full">
      {/* ═══ Left: Badge overview ═══ */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-w-0">
        {/* Badge type selector + actions bar */}
        <div className="bg-white rounded-lg shadow px-4 py-3 space-y-3">
          {/* Type selector */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            {BUILTIN_TYPES.map((bt) => {
              const Icon = bt.icon;
              const isActive = badgeType === bt.key;
              return (
                <button
                  key={bt.key}
                  onClick={() => { setBadgeType(bt.key); setSelectedTemplate(null); }}
                  className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors ${
                    isActive ? bt.activeColor : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  <Icon size={14} />
                  <span>{bt.label}</span>
                </button>
              );
            })}
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-2">
            {customTemplates.length > 0 && (
              <select
                value={selectedTemplate || ''}
                onChange={(e) => setSelectedTemplate(e.target.value || null)}
                className="px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="">内置模板</option>
                {customTemplates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            )}

            <button onClick={handlePreviewSelected}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 text-gray-700 rounded text-sm hover:bg-gray-50"
            >
              <Eye size={15} /> 预览
            </button>

            <button onClick={handleGenerateSelected}
              disabled={totalActive === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              <Download size={15} /> 打印 ({totalActive}人)
            </button>

            <button
              onClick={() => { setEditingTemplate(null); setDesignerOpen(true); }}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-indigo-300 text-indigo-600 rounded text-sm hover:bg-indigo-50"
            >
              <Plus size={15} /> 设计模板
            </button>

            <div className="flex items-center gap-1 text-xs text-gray-500 ml-auto">
              <Users size={14} />
              {roleGroups.length} 个角色 · {totalActive} 人
            </div>
          </div>
        </div>

        {/* ── Built-in template preview (scaled, no scrollbar) ── */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-4 py-2 border-b border-gray-100 flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500">
              当前模板：{selectedTemplate
                ? customTemplates.find((t) => t.id === selectedTemplate)?.name || '自定义'
                : `${currentBuiltin.label}（内置）`}
            </span>
            <span className="text-[10px] text-gray-400">{currentBuiltin.desc}</span>
          </div>
          <div className="bg-gray-100 flex justify-center py-3">
            <ScaledIframe
              src={mainPreviewUrl}
              nativeW={currentBuiltin.nativeW}
              nativeH={currentBuiltin.nativeH}
              boxW={MAIN_BOX_W}
              boxH={MAIN_BOX_H}
              title={currentBuiltin.label}
              onClick={handlePreviewSelected}
            />
          </div>
        </div>

        {/* Custom templates gallery (scaled thumbnails) */}
        {customTemplates.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">自定义模板</h3>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {customTemplates.map((t) => {
                const custNW = currentBuiltin.nativeW;
                const custNH = currentBuiltin.nativeH;
                return (
                  <div
                    key={t.id}
                    onClick={() => setSelectedTemplate(t.id === selectedTemplate ? null : t.id)}
                    className={`bg-white rounded-lg border overflow-hidden hover:shadow-md transition-all cursor-pointer group ${
                      selectedTemplate === t.id
                        ? 'border-indigo-500 ring-2 ring-indigo-200'
                        : 'border-gray-200'
                    }`}
                  >
                    {/* Scaled thumbnail */}
                    <div className="bg-gray-100 flex justify-center py-2">
                      <ScaledIframe
                        src={apiClient.getBadgePreviewUrl(eventId, t.template_type, t.id)}
                        nativeW={custNW}
                        nativeH={custNH}
                        boxW={CUST_BOX_W}
                        boxH={CUST_BOX_H}
                        title={t.name}
                      />
                    </div>
                    {/* Name + actions */}
                    <div className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-gray-900 truncate flex-1">
                          {t.name}
                        </span>
                        <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => { e.stopPropagation(); setEditingTemplate(t); setDesignerOpen(true); }}
                            className="p-1 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded"
                            title="编辑"
                          ><Pencil size={11} /></button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              if (confirm('确定删除此模板？')) deleteMutation.mutate(t.id);
                            }}
                            className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded"
                            title="删除"
                          ><Trash2 size={11} /></button>
                        </div>
                      </div>
                      {selectedTemplate === t.id && (
                        <div className="mt-1.5 flex gap-1">
                          <button
                            onClick={(e) => { e.stopPropagation(); handlePreview(t.template_type, t.id); }}
                            className="flex-1 flex items-center justify-center gap-1 px-2 py-1 text-[10px] font-medium text-gray-600 bg-gray-50 rounded hover:bg-gray-100"
                          ><Eye size={10} /> 大图</button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleGenerate(t.template_type, t.id); }}
                            className="flex-1 flex items-center justify-center gap-1 px-2 py-1 text-[10px] font-medium text-indigo-600 bg-indigo-50 rounded hover:bg-indigo-100"
                          ><Download size={10} /> 打印</button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Role-grouped attendee list */}
        <div className="space-y-2">
          {roleGroups.length === 0 ? (
            <div className="bg-white rounded-lg shadow p-8 text-center">
              <Users size={40} className="mx-auto mb-3 text-gray-300" />
              <p className="text-sm text-gray-500">
                还没有参会人员，请先在「参会人」页面添加
              </p>
            </div>
          ) : (
            roleGroups.map((group) => (
              <div key={group.role} className="bg-white rounded-lg shadow overflow-hidden">
                <button
                  onClick={() => toggleRole(group.role)}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
                >
                  {expandedRoles.has(group.role)
                    ? <ChevronDown size={16} className="text-gray-400" />
                    : <ChevronRight size={16} className="text-gray-400" />}
                  <span className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ backgroundColor: group.color }} />
                  <span className="text-sm font-semibold text-gray-900">{group.role}</span>
                  <span className="text-xs text-gray-500">{group.members.length} 人</span>
                  <div className="ml-auto flex items-center gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleGenerate(currentBuiltin.templateName, selectedTemplate || undefined, [group.role]);
                      }}
                      className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-gray-500 bg-gray-100 rounded hover:bg-indigo-100 hover:text-indigo-600 transition-colors"
                      title={`仅生成「${group.role}」的铭牌`}
                    ><Download size={10} /> 生成</button>
                    <div
                      className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold"
                      style={{
                        backgroundColor: `${group.color}20`,
                        color: group.color,
                        border: `1px solid ${group.color}40`,
                      }}
                    ><Tag size={10} /> {group.role}</div>
                  </div>
                </button>

                {expandedRoles.has(group.role) && (
                  <div className="border-t border-gray-100 divide-y divide-gray-50">
                    {group.members.map((a) => (
                      <div key={a.id} className="flex items-center gap-3 px-4 py-2 pl-12">
                        <span className="text-sm font-medium text-gray-900 w-20 truncate">{a.name}</span>
                        <span className="text-xs text-gray-500 truncate">{a.title || ''}</span>
                        <span className="text-xs text-gray-400 truncate">{a.organization || ''}</span>
                        <span className="text-[10px] text-gray-400 ml-auto">P{a.priority}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* ═══ Right: AI Assistant ═══ */}
      <SubAgentPanel
        eventId={eventId}
        scope="badge"
        title="铭牌设计助手"
        placeholder="如：生成竖版会议胸牌、设计中英双语桌签..."
        welcomeMessage={`我可以帮你：
1. 生成铭牌 — 如「生成全部胸牌」「只生成桌签」
2. 设计模板 — 如「设计一个学术风格的胸牌」
3. 查看预览 — 如「预览当前参会人铭牌效果」
4. 自定义风格 — 如「深色底白字、加二维码」
（铭牌输出为 HTML 页面，浏览器 Ctrl+P 打印即可）`}
      />

      {/* ═══ Badge Designer Modal ═══ */}
      {designerOpen && (
        <BadgeDesigner
          templateType={customTplType}
          onSave={handleDesignerSave}
          onCancel={() => { setDesignerOpen(false); setEditingTemplate(null); }}
        />
      )}

      {/* ═══ Template Preview Modal (scaled, no scrollbar) ═══ */}
      {previewUrl && (
        <PreviewModal
          url={previewUrl}
          nativeW={currentBuiltin.nativeW}
          nativeH={currentBuiltin.nativeH}
          totalActive={totalActive}
          onClose={() => setPreviewUrl(null)}
          onPrint={() => { handleGenerateSelected(); setPreviewUrl(null); }}
        />
      )}
    </div>
  );
}

/* ───── Full-size preview modal (scaled, no scrollbar) ───── */

function PreviewModal({
  url, nativeW, nativeH, totalActive, onClose, onPrint,
}: {
  url: string;
  nativeW: number;
  nativeH: number;
  totalActive: number;
  onClose: () => void;
  onPrint: () => void;
}) {
  const maxW = Math.min(window.innerWidth * 0.8, 600);
  const maxH = window.innerHeight * 0.7;
  const scale = fitScale(nativeW, nativeH, maxW, maxH);
  const dispW = nativeW * scale;
  const dispH = nativeH * scale;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div className="bg-white rounded-xl shadow-2xl flex flex-col"
        style={{ width: `${dispW + 48}px` }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="text-sm font-semibold text-gray-900">铭牌预览</h3>
          <button onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
          >&times;</button>
        </div>
        <div className="flex justify-center p-5 bg-gray-100">
          <div style={{
            width: `${dispW}px`,
            height: `${dispH}px`,
            overflow: 'hidden',
            borderRadius: '6px',
            boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
          }}>
            <iframe
              src={url}
              scrolling="no"
              className="border-0"
              style={{
                width: `${nativeW}px`,
                height: `${nativeH}px`,
                transform: `scale(${scale})`,
                transformOrigin: 'top left',
              }}
              title="Badge Preview"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t">
          <button onClick={onClose}
            className="px-3 py-1.5 text-sm text-gray-600 border rounded hover:bg-gray-50"
          >关闭</button>
          <button onClick={onPrint}
            disabled={totalActive === 0}
            className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
          >打印全部 ({totalActive}人)</button>
        </div>
      </div>
    </div>
  );
}
