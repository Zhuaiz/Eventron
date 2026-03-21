import { useState, useEffect, useMemo, useCallback } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  X, Plus, Trash2, GripVertical, ChevronUp, ChevronDown, Code, Palette,
} from 'lucide-react';
import { apiClient } from '../lib/api';

/* ───── Types ───── */

interface BadgeTemplate {
  id: string;
  name: string;
  template_type: string;
  html_template: string;
  css: string;
  style_category?: string;
}

interface BadgeTemplateModalProps {
  isOpen: boolean;
  template?: BadgeTemplate | null;
  onClose?: () => void;
  onModalClose: () => void;
}

/** A single visual element on the badge. */
interface BadgeElement {
  id: string;
  type: 'text' | 'variable';
  /** Display label in the editor list */
  label: string;
  /** Jinja2 variable key (for variable type), or literal text */
  value: string;
  x: number;       // % from left
  y: number;       // % from top
  fontSize: number; // px
  fontWeight: 'normal' | 'bold';
  color: string;
  textAlign: 'left' | 'center' | 'right';
  visible: boolean;
}

/* ───── Constants ───── */

const TEMPLATE_TYPES = [
  { value: 'badge', label: '胸牌' },
  { value: 'tent_card', label: '桌签' },
];

const STYLE_CATEGORIES = [
  { value: 'business', label: '商务' },
  { value: 'academic', label: '学术' },
  { value: 'government', label: '政府' },
  { value: 'custom', label: '自定义' },
];

const VARIABLE_PRESETS: { label: string; value: string }[] = [
  { label: '活动名称', value: 'event_name' },
  { label: '姓名', value: 'name' },
  { label: '职务', value: 'title' },
  { label: '单位', value: 'organization' },
  { label: '角色', value: 'role_label' },
  { label: '活动日期', value: 'event_date' },
];

const SAMPLE_DATA: Record<string, string> = {
  event_name: '示例活动 · 年度峰会',
  name: '张三',
  title: '产品总监',
  organization: '示例科技有限公司',
  role_label: '嘉宾',
  event_date: '2026年3月23日',
};

let _elemId = 0;
function nextId() { return `el_${++_elemId}_${Date.now()}`; }

/** Default elements for a new badge */
function defaultElements(): BadgeElement[] {
  return [
    { id: nextId(), type: 'variable', label: '活动名称', value: 'event_name',
      x: 50, y: 8, fontSize: 14, fontWeight: 'bold', color: '#ffffff',
      textAlign: 'center', visible: true },
    { id: nextId(), type: 'variable', label: '姓名', value: 'name',
      x: 50, y: 42, fontSize: 28, fontWeight: 'bold', color: '#1a1a2e',
      textAlign: 'center', visible: true },
    { id: nextId(), type: 'variable', label: '职务', value: 'title',
      x: 50, y: 56, fontSize: 13, fontWeight: 'normal', color: '#555555',
      textAlign: 'center', visible: true },
    { id: nextId(), type: 'variable', label: '单位', value: 'organization',
      x: 50, y: 64, fontSize: 12, fontWeight: 'normal', color: '#777777',
      textAlign: 'center', visible: true },
    { id: nextId(), type: 'variable', label: '角色', value: 'role_label',
      x: 50, y: 88, fontSize: 12, fontWeight: 'bold', color: '#ffffff',
      textAlign: 'center', visible: true },
  ];
}

/* ───── HTML / CSS generators from elements ───── */

function generateHtml(elements: BadgeElement[]): string {
  const visible = elements.filter((e) => e.visible);
  const divs = visible.map((el) => {
    const content = el.type === 'variable'
      ? `{{ attendees[0].${el.value}|default('${SAMPLE_DATA[el.value] || ''}') }}`
      : el.value;
    return `  <div class="el-${el.id}">${content}</div>`;
  });
  return `<div class="badge-container">\n${divs.join('\n')}\n</div>`;
}

function generateCss(
  elements: BadgeElement[],
  bgColor: string,
  badgeW: number,
  badgeH: number,
): string {
  let css = `/* Auto-generated badge CSS */
@page { size: ${badgeW}mm ${badgeH}mm; margin: 0; }

.badge-container {
  position: relative;
  width: ${badgeW}mm;
  height: ${badgeH}mm;
  background: ${bgColor};
  overflow: hidden;
  font-family: "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  box-sizing: border-box;
}
`;
  const visible = elements.filter((e) => e.visible);
  for (const el of visible) {
    const ta = el.textAlign;
    let transform = 'translateY(-50%)';
    if (ta === 'center') transform = 'translate(-50%, -50%)';
    else if (ta === 'right') transform = 'translate(-100%, -50%)';
    css += `
.el-${el.id} {
  position: absolute;
  left: ${el.x}%;
  top: ${el.y}%;
  transform: ${transform};
  font-size: ${el.fontSize}px;
  font-weight: ${el.fontWeight};
  color: ${el.color};
  text-align: ${ta};
  white-space: nowrap;
}
`;
  }
  return css;
}

/* ───── Parsing existing HTML/CSS back to elements (best-effort) ───── */

function parseExistingTemplate(html: string, css: string): BadgeElement[] | null {
  // Only parse templates we generated (they contain .el_ classes)
  if (!html.includes('el_') || !css.includes('el_')) return null;
  const elRegex = /<div class="el-([^"]+)">([^<]*)<\/div>/g;
  const elements: BadgeElement[] = [];
  let m;
  while ((m = elRegex.exec(html)) !== null) {
    const elId = m[1];
    const content = m[2];
    // Try to detect if it's a Jinja2 variable
    const varMatch = content.match(/\{\{\s*attendees\[0\]\.(\w+)/);
    const isVar = !!varMatch;
    const varKey = varMatch ? varMatch[1] : '';
    const preset = VARIABLE_PRESETS.find((p) => p.value === varKey);

    // Parse CSS for this element
    const cssBlock = css.match(
      new RegExp(`\\.el-${elId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]+)\\}`)
    );
    const props: Record<string, string> = {};
    if (cssBlock) {
      cssBlock[1].split(';').forEach((line) => {
        const [k, v] = line.split(':').map((s) => s.trim());
        if (k && v) props[k] = v;
      });
    }

    elements.push({
      id: elId,
      type: isVar ? 'variable' : 'text',
      label: isVar ? (preset?.label || varKey) : '自定义文本',
      value: isVar ? varKey : content,
      x: parseFloat(props['left']) || 50,
      y: parseFloat(props['top']) || 50,
      fontSize: parseInt(props['font-size']) || 14,
      fontWeight: (props['font-weight'] as 'bold' | 'normal') || 'normal',
      color: props['color'] || '#000000',
      textAlign: (props['text-align'] as 'left' | 'center' | 'right') || 'center',
      visible: true,
    });
  }
  return elements.length > 0 ? elements : null;
}

/* ───── Component ───── */

export function BadgeTemplateModal({
  isOpen,
  template,
  onClose,
  onModalClose,
}: BadgeTemplateModalProps) {
  const [name, setName] = useState('');
  const [templateType, setTemplateType] = useState('badge');
  const [styleCategory, setStyleCategory] = useState('custom');
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'visual' | 'code'>('visual');

  // Visual editor state
  const [elements, setElements] = useState<BadgeElement[]>(defaultElements);
  const [bgColor, setBgColor] = useState('#0a1e3d');
  const [badgeW, setBadgeW] = useState(90);
  const [badgeH, setBadgeH] = useState(130);
  const [selectedElId, setSelectedElId] = useState<string | null>(null);

  // Code editor state (synced from visual)
  const [htmlCode, setHtmlCode] = useState('');
  const [cssCode, setCssCode] = useState('');

  const queryClient = useQueryClient();

  /* Sync visual → code whenever elements change */
  const generatedHtml = useMemo(() => generateHtml(elements), [elements]);
  const generatedCss = useMemo(
    () => generateCss(elements, bgColor, badgeW, badgeH),
    [elements, bgColor, badgeW, badgeH],
  );

  useEffect(() => {
    if (mode === 'visual') {
      setHtmlCode(generatedHtml);
      setCssCode(generatedCss);
    }
  }, [generatedHtml, generatedCss, mode]);

  /* Init from template or reset */
  useEffect(() => {
    if (!isOpen) return;
    if (template) {
      setName(template.name);
      setTemplateType(template.template_type);
      setStyleCategory(template.style_category || 'custom');
      setError('');
      // Try to parse existing template into visual elements
      const parsed = parseExistingTemplate(template.html_template, template.css);
      if (parsed) {
        setElements(parsed);
        setMode('visual');
      } else {
        // Fallback to code mode for templates we can't parse
        setHtmlCode(template.html_template);
        setCssCode(template.css);
        setMode('code');
      }
      // Try to parse badge dimensions from CSS
      const sizeMatch = template.css.match(
        /@page\s*\{\s*size:\s*([\d.]+)mm\s+([\d.]+)mm/
      );
      if (sizeMatch) {
        setBadgeW(parseFloat(sizeMatch[1]));
        setBadgeH(parseFloat(sizeMatch[2]));
      }
      const bgMatch = template.css.match(/background:\s*([^;]+);/);
      if (bgMatch) setBgColor(bgMatch[1].trim());
    } else {
      setName('');
      setTemplateType('badge');
      setStyleCategory('custom');
      setError('');
      setElements(defaultElements());
      setBgColor('#0a1e3d');
      setBadgeW(90);
      setBadgeH(130);
      setMode('visual');
      setSelectedElId(null);
    }
  }, [template, isOpen]);

  /* Element manipulation */
  const updateElement = useCallback((id: string, patch: Partial<BadgeElement>) => {
    setElements((prev) => prev.map((el) => el.id === id ? { ...el, ...patch } : el));
  }, []);

  const removeElement = useCallback((id: string) => {
    setElements((prev) => prev.filter((el) => el.id !== id));
    if (selectedElId === id) setSelectedElId(null);
  }, [selectedElId]);

  const moveElement = useCallback((id: string, dir: -1 | 1) => {
    setElements((prev) => {
      const idx = prev.findIndex((el) => el.id === id);
      if (idx < 0) return prev;
      const newIdx = idx + dir;
      if (newIdx < 0 || newIdx >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[newIdx]] = [next[newIdx], next[idx]];
      return next;
    });
  }, []);

  const addVariable = useCallback((varKey: string) => {
    const preset = VARIABLE_PRESETS.find((p) => p.value === varKey);
    const el: BadgeElement = {
      id: nextId(),
      type: 'variable',
      label: preset?.label || varKey,
      value: varKey,
      x: 50, y: 50, fontSize: 14, fontWeight: 'normal',
      color: '#333333', textAlign: 'center', visible: true,
    };
    setElements((prev) => [...prev, el]);
    setSelectedElId(el.id);
  }, []);

  const addText = useCallback(() => {
    const el: BadgeElement = {
      id: nextId(),
      type: 'text',
      label: '自定义文本',
      value: '自定义文本',
      x: 50, y: 50, fontSize: 14, fontWeight: 'normal',
      color: '#333333', textAlign: 'center', visible: true,
    };
    setElements((prev) => [...prev, el]);
    setSelectedElId(el.id);
  }, []);

  /* Save */
  const createMutation = useMutation({
    mutationFn: async () => {
      const finalHtml = mode === 'visual' ? generatedHtml : htmlCode;
      const finalCss = mode === 'visual' ? generatedCss : cssCode;
      const payload = {
        name,
        template_type: templateType,
        html_template: finalHtml,
        css: finalCss,
        style_category: styleCategory,
      };
      if (template) {
        return apiClient.updateBadgeTemplate(template.id, payload);
      }
      return apiClient.createBadgeTemplate(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['badge-templates'] });
      onModalClose();
      if (onClose) onClose();
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : '保存失败');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) { setError('请填写模板名称'); return; }
    createMutation.mutate();
  };

  if (!isOpen) return null;

  const selectedEl = elements.find((el) => el.id === selectedElId) || null;

  /* ---- Live preview HTML (inline, not iframe) ---- */
  const previewScale = 1.8; // px-per-mm for the live preview canvas
  const canvasW = badgeW * previewScale;
  const canvasH = badgeH * previewScale;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-lg flex flex-col"
        style={{ width: '980px', maxHeight: '92vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
          <h2 className="text-xl font-bold text-gray-900">
            {template ? '编辑模板' : '新建模板'}
          </h2>
          <div className="flex items-center gap-3">
            {/* Mode toggle */}
            <div className="flex border rounded-lg overflow-hidden text-sm">
              <button
                type="button"
                onClick={() => setMode('visual')}
                className={`flex items-center gap-1 px-3 py-1.5 ${
                  mode === 'visual'
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <Palette size={14} /> 可视化
              </button>
              <button
                type="button"
                onClick={() => {
                  if (mode === 'visual') {
                    setHtmlCode(generatedHtml);
                    setCssCode(generatedCss);
                  }
                  setMode('code');
                }}
                className={`flex items-center gap-1 px-3 py-1.5 ${
                  mode === 'code'
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                <Code size={14} /> 代码
              </button>
            </div>
            <button
              onClick={onModalClose}
              className="p-1 hover:bg-gray-100 rounded"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-hidden flex flex-col">
          {/* Top meta row */}
          <div className="px-6 pt-4 pb-2 grid grid-cols-4 gap-3 shrink-0">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">模板名称 *</label>
              <input
                type="text" value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-2.5 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="输入名称"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">类型</label>
              <select value={templateType}
                onChange={(e) => setTemplateType(e.target.value)}
                className="w-full px-2.5 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {TEMPLATE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">风格</label>
              <select value={styleCategory}
                onChange={(e) => setStyleCategory(e.target.value)}
                className="w-full px-2.5 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {STYLE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <label className="block text-xs font-medium text-gray-600 mb-1">尺寸 (mm)</label>
                <div className="flex gap-1 items-center text-sm">
                  <input type="number" value={badgeW}
                    onChange={(e) => setBadgeW(Number(e.target.value) || 90)}
                    className="w-16 px-2 py-1.5 border border-gray-300 rounded text-center"
                  />
                  <span className="text-gray-400">×</span>
                  <input type="number" value={badgeH}
                    onChange={(e) => setBadgeH(Number(e.target.value) || 130)}
                    className="w-16 px-2 py-1.5 border border-gray-300 rounded text-center"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Main area: element list + live preview */}
          <div className="flex-1 overflow-hidden flex px-6 py-3 gap-4">
            {mode === 'visual' ? (
              <>
                {/* Left: element list + properties */}
                <div className="w-[340px] shrink-0 flex flex-col overflow-hidden">
                  {/* Add buttons */}
                  <div className="flex gap-2 mb-2 shrink-0">
                    <div className="relative group flex-1">
                      <button type="button"
                        className="w-full flex items-center justify-center gap-1 px-2 py-1.5 border border-dashed border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 text-xs"
                      >
                        <Plus size={12} /> 添加变量
                      </button>
                      {/* Dropdown */}
                      <div className="absolute top-full left-0 mt-1 w-full bg-white border rounded-lg shadow-lg z-10 hidden group-hover:block">
                        {VARIABLE_PRESETS.map((v) => (
                          <button key={v.value} type="button"
                            onClick={() => addVariable(v.value)}
                            className="w-full text-left px-3 py-1.5 text-xs hover:bg-indigo-50 hover:text-indigo-700"
                          >
                            {v.label} <span className="text-gray-400 ml-1">{`{{ ${v.value} }}`}</span>
                          </button>
                        ))}
                      </div>
                    </div>
                    <button type="button" onClick={addText}
                      className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 border border-dashed border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 text-xs"
                    >
                      <Plus size={12} /> 添加文本
                    </button>
                  </div>

                  {/* Element list */}
                  <div className="flex-1 overflow-y-auto space-y-1 pr-1">
                    {elements.map((el, idx) => (
                      <div key={el.id}
                        onClick={() => setSelectedElId(el.id)}
                        className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg cursor-pointer text-xs transition-colors ${
                          selectedElId === el.id
                            ? 'bg-indigo-50 border border-indigo-300'
                            : 'bg-gray-50 border border-transparent hover:bg-gray-100'
                        }`}
                      >
                        <GripVertical size={12} className="text-gray-300 shrink-0" />
                        <input type="checkbox" checked={el.visible}
                          onChange={(e) => { e.stopPropagation(); updateElement(el.id, { visible: e.target.checked }); }}
                          className="shrink-0"
                        />
                        <span className="flex-1 truncate font-medium text-gray-700">
                          {el.label}
                          {el.type === 'variable' && (
                            <span className="ml-1 text-gray-400 font-normal">{`{{ ${el.value} }}`}</span>
                          )}
                        </span>
                        <button type="button" onClick={(e) => { e.stopPropagation(); moveElement(el.id, -1); }}
                          disabled={idx === 0}
                          className="p-0.5 hover:bg-gray-200 rounded disabled:opacity-20"
                        ><ChevronUp size={12} /></button>
                        <button type="button" onClick={(e) => { e.stopPropagation(); moveElement(el.id, 1); }}
                          disabled={idx === elements.length - 1}
                          className="p-0.5 hover:bg-gray-200 rounded disabled:opacity-20"
                        ><ChevronDown size={12} /></button>
                        <button type="button" onClick={(e) => { e.stopPropagation(); removeElement(el.id); }}
                          className="p-0.5 hover:bg-red-100 text-red-400 hover:text-red-600 rounded"
                        ><Trash2 size={12} /></button>
                      </div>
                    ))}
                  </div>

                  {/* Selected element properties */}
                  {selectedEl && (
                    <div className="mt-2 pt-2 border-t space-y-2 shrink-0">
                      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                        元素属性
                      </div>
                      {selectedEl.type === 'text' && (
                        <div>
                          <label className="block text-xs text-gray-500 mb-0.5">文本内容</label>
                          <input type="text" value={selectedEl.value}
                            onChange={(e) => updateElement(selectedEl.id, { value: e.target.value })}
                            className="w-full px-2 py-1 border rounded text-xs"
                          />
                        </div>
                      )}
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <label className="block text-xs text-gray-500 mb-0.5">X 位置 (%)</label>
                          <input type="number" min={0} max={100}
                            value={selectedEl.x}
                            onChange={(e) => updateElement(selectedEl.id, { x: Number(e.target.value) })}
                            className="w-full px-2 py-1 border rounded text-xs"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-gray-500 mb-0.5">Y 位置 (%)</label>
                          <input type="number" min={0} max={100}
                            value={selectedEl.y}
                            onChange={(e) => updateElement(selectedEl.id, { y: Number(e.target.value) })}
                            className="w-full px-2 py-1 border rounded text-xs"
                          />
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <label className="block text-xs text-gray-500 mb-0.5">字号</label>
                          <input type="number" min={8} max={80}
                            value={selectedEl.fontSize}
                            onChange={(e) => updateElement(selectedEl.id, { fontSize: Number(e.target.value) })}
                            className="w-full px-2 py-1 border rounded text-xs"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-gray-500 mb-0.5">粗细</label>
                          <select value={selectedEl.fontWeight}
                            onChange={(e) => updateElement(selectedEl.id, { fontWeight: e.target.value as 'normal' | 'bold' })}
                            className="w-full px-2 py-1 border rounded text-xs"
                          >
                            <option value="normal">常规</option>
                            <option value="bold">加粗</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-xs text-gray-500 mb-0.5">对齐</label>
                          <select value={selectedEl.textAlign}
                            onChange={(e) => updateElement(selectedEl.id, { textAlign: e.target.value as 'left' | 'center' | 'right' })}
                            className="w-full px-2 py-1 border rounded text-xs"
                          >
                            <option value="left">左</option>
                            <option value="center">中</option>
                            <option value="right">右</option>
                          </select>
                        </div>
                      </div>
                      <div>
                        <label className="block text-xs text-gray-500 mb-0.5">颜色</label>
                        <div className="flex items-center gap-2">
                          <input type="color" value={selectedEl.color}
                            onChange={(e) => updateElement(selectedEl.id, { color: e.target.value })}
                            className="w-8 h-8 rounded border cursor-pointer"
                          />
                          <input type="text" value={selectedEl.color}
                            onChange={(e) => updateElement(selectedEl.id, { color: e.target.value })}
                            className="flex-1 px-2 py-1 border rounded text-xs font-mono"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Background color */}
                  <div className="mt-2 pt-2 border-t shrink-0">
                    <label className="block text-xs text-gray-500 mb-1">背景色</label>
                    <div className="flex items-center gap-2">
                      <input type="color" value={bgColor.startsWith('#') ? bgColor : '#0a1e3d'}
                        onChange={(e) => setBgColor(e.target.value)}
                        className="w-8 h-8 rounded border cursor-pointer"
                      />
                      <input type="text" value={bgColor}
                        onChange={(e) => setBgColor(e.target.value)}
                        className="flex-1 px-2 py-1 border rounded text-xs font-mono"
                        placeholder="linear-gradient(...) or #hex"
                      />
                    </div>
                  </div>
                </div>

                {/* Right: live preview canvas */}
                <div className="flex-1 flex items-start justify-center overflow-auto bg-gray-100 rounded-lg p-4">
                  <div style={{
                    width: `${canvasW}px`,
                    height: `${canvasH}px`,
                    background: bgColor,
                    position: 'relative',
                    overflow: 'hidden',
                    borderRadius: '4px',
                    boxShadow: '0 4px 20px rgba(0,0,0,0.25)',
                    fontFamily: '"Noto Sans CJK SC", "PingFang SC", sans-serif',
                  }}>
                    {elements.filter((e) => e.visible).map((el) => {
                      const content = el.type === 'variable'
                        ? SAMPLE_DATA[el.value] || el.value
                        : el.value;
                      const ta = el.textAlign;
                      let transform = 'translateY(-50%)';
                      if (ta === 'center') transform = 'translate(-50%, -50%)';
                      else if (ta === 'right') transform = 'translate(-100%, -50%)';
                      return (
                        <div key={el.id}
                          onClick={() => setSelectedElId(el.id)}
                          style={{
                            position: 'absolute',
                            left: `${el.x}%`,
                            top: `${el.y}%`,
                            transform,
                            fontSize: `${el.fontSize * (previewScale / 3.78)}px`,
                            fontWeight: el.fontWeight,
                            color: el.color,
                            textAlign: ta,
                            whiteSpace: 'nowrap',
                            cursor: 'pointer',
                            outline: selectedElId === el.id
                              ? '2px solid rgba(99,102,241,0.7)' : 'none',
                            outlineOffset: '2px',
                            borderRadius: '2px',
                          }}
                        >
                          {content}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : (
              /* Code mode */
              <div className="flex-1 flex gap-4 overflow-hidden">
                <div className="flex-1 flex flex-col overflow-hidden">
                  <label className="block text-xs font-medium text-gray-600 mb-1">HTML 模板</label>
                  <textarea value={htmlCode}
                    onChange={(e) => setHtmlCode(e.target.value)}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg font-mono text-xs resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div className="flex-1 flex flex-col overflow-hidden">
                  <label className="block text-xs font-medium text-gray-600 mb-1">CSS 样式</label>
                  <textarea value={cssCode}
                    onChange={(e) => setCssCode(e.target.value)}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg font-mono text-xs resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="mx-6 mb-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Footer */}
          <div className="px-6 py-3 border-t flex gap-3 shrink-0">
            <button type="button" onClick={onModalClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 font-medium hover:bg-gray-50 transition-colors"
            >
              取消
            </button>
            <button type="submit" disabled={createMutation.isPending}
              className="flex-1 px-4 py-2 bg-indigo-600 text-white font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {createMutation.isPending ? '保存中...' : template ? '更新' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
