/**
 * BadgeDesigner — Visual drag-and-drop badge template editor.
 *
 * Users drag elements (name, title, org, role, logo, QR) onto a canvas,
 * customize fonts/colors/positions, upload images, and save as a template.
 * Outputs Jinja2 HTML + CSS for WeasyPrint PDF rendering.
 */
import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import {
  X, Plus, Save, Eye, Trash2, Type, Image, QrCode,
  Tag, Building2, Briefcase, Move, RotateCcw, Upload,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface DesignElement {
  id: string;
  type: 'text' | 'image' | 'qr';
  /** Which attendee field this element maps to */
  field: string;
  /** Display label in the element list */
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  fontSize: number;
  fontWeight: string;
  color: string;
  textAlign: 'left' | 'center' | 'right';
  /** For image type: data URI or URL */
  imageSrc?: string;
  /** Whether this is a static element (logo) vs dynamic (attendee field) */
  isStatic: boolean;
}

interface BadgeDesignerProps {
  /** Initial template to edit (null = new template) */
  initialElements?: DesignElement[];
  initialBackground?: BackgroundConfig;
  templateType?: 'badge' | 'tent_card';
  onSave: (data: {
    html_template: string;
    css: string;
    elements: DesignElement[];
    background: BackgroundConfig;
  }) => void;
  onCancel: () => void;
}

interface BackgroundConfig {
  type: 'solid' | 'gradient' | 'image';
  color1: string;
  color2: string;
  gradientAngle: number;
  imageUrl: string;
}

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

/** Badge physical sizes (mm) — displayed as px at 3x for editing */
const BADGE_SIZES = {
  badge: { w: 90, h: 54, label: '胸牌 (90×54mm)' },
  tent_card: { w: 210, h: 99, label: '桌签 (210×99mm)' },
} as const;

const SCALE = 3; // mm to px scale for canvas

const ELEMENT_PRESETS: Omit<DesignElement, 'id' | 'x' | 'y'>[] = [
  {
    type: 'text', field: 'name', label: '姓名',
    width: 200, height: 40, fontSize: 20, fontWeight: '700',
    color: '#ffffff', textAlign: 'center', isStatic: false,
  },
  {
    type: 'text', field: 'title', label: '职位',
    width: 160, height: 24, fontSize: 10, fontWeight: '400',
    color: '#ffffffcc', textAlign: 'center', isStatic: false,
  },
  {
    type: 'text', field: 'organization', label: '单位',
    width: 160, height: 24, fontSize: 9, fontWeight: '400',
    color: '#ffffffbb', textAlign: 'center', isStatic: false,
  },
  {
    type: 'text', field: 'role_label', label: '角色标签',
    width: 80, height: 22, fontSize: 8, fontWeight: '600',
    color: '#ffffff', textAlign: 'center', isStatic: false,
  },
  {
    type: 'text', field: 'event_name', label: '活动名称',
    width: 200, height: 24, fontSize: 10, fontWeight: '600',
    color: '#ffffffdd', textAlign: 'center', isStatic: true,
  },
  {
    type: 'text', field: 'event_date', label: '活动日期',
    width: 120, height: 20, fontSize: 8, fontWeight: '400',
    color: '#ffffff99', textAlign: 'center', isStatic: true,
  },
  {
    type: 'image', field: 'logo', label: 'Logo',
    width: 60, height: 60, fontSize: 0, fontWeight: '400',
    color: '', textAlign: 'center', isStatic: true, imageSrc: '',
  },
  {
    type: 'qr', field: 'qr_data', label: '二维码',
    width: 40, height: 40, fontSize: 0, fontWeight: '400',
    color: '', textAlign: 'center', isStatic: false,
  },
];

const ICON_MAP: Record<string, React.ReactNode> = {
  name: <Type size={13} />,
  title: <Briefcase size={13} />,
  organization: <Building2 size={13} />,
  role_label: <Tag size={13} />,
  event_name: <Type size={13} />,
  event_date: <Type size={13} />,
  logo: <Image size={13} />,
  qr_data: <QrCode size={13} />,
};

/** Sample data for preview */
const SAMPLE = {
  name: '张三',
  title: '产品总监',
  organization: '示例科技有限公司',
  role_label: '甲方嘉宾',
  event_name: '2026 年度技术大会',
  event_date: '2026年03月21日',
};

let _nextId = 1;
function nextId() {
  return `el_${_nextId++}`;
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export function BadgeDesigner({
  initialElements,
  initialBackground,
  templateType = 'badge',
  onSave,
  onCancel,
}: BadgeDesignerProps) {
  const size = BADGE_SIZES[templateType];
  const canvasW = size.w * SCALE;
  const canvasH = size.h * SCALE;

  const [elements, setElements] = useState<DesignElement[]>(
    initialElements || getDefaultElements(templateType),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const [background, setBackground] = useState<BackgroundConfig>(
    initialBackground || {
      type: 'gradient',
      color1: '#1a1a2e',
      color2: '#0f3460',
      gradientAngle: 135,
      imageUrl: '',
    },
  );
  const [showPreview, setShowPreview] = useState(false);

  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    elId: string;
    offsetX: number;
    offsetY: number;
  } | null>(null);

  const selectedEl = useMemo(
    () => elements.find((e) => e.id === selected) || null,
    [elements, selected],
  );

  // ── Drag handlers ──
  const handleMouseDown = useCallback(
    (e: React.MouseEvent, elId: string) => {
      e.stopPropagation();
      const el = elements.find((el) => el.id === elId);
      if (!el) return;
      setSelected(elId);
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      dragRef.current = {
        elId,
        offsetX: e.clientX - rect.left - el.x,
        offsetY: e.clientY - rect.top - el.y,
      };
    },
    [elements],
  );

  useEffect(() => {
    const handleMove = (e: MouseEvent) => {
      if (!dragRef.current || !canvasRef.current) return;
      const rect = canvasRef.current.getBoundingClientRect();
      const x = Math.max(0, Math.min(canvasW, e.clientX - rect.left - dragRef.current.offsetX));
      const y = Math.max(0, Math.min(canvasH, e.clientY - rect.top - dragRef.current.offsetY));
      setElements((prev) =>
        prev.map((el) =>
          el.id === dragRef.current!.elId ? { ...el, x: Math.round(x), y: Math.round(y) } : el,
        ),
      );
    };
    const handleUp = () => {
      dragRef.current = null;
    };
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [canvasW, canvasH]);

  // ── Element operations ──
  const addElement = (preset: (typeof ELEMENT_PRESETS)[number]) => {
    const id = nextId();
    const el: DesignElement = {
      ...preset,
      id,
      x: (canvasW - preset.width) / 2,
      y: elements.length * 30 + 20,
    };
    setElements((prev) => [...prev, el]);
    setSelected(id);
  };

  const updateSelected = (patch: Partial<DesignElement>) => {
    if (!selected) return;
    setElements((prev) =>
      prev.map((el) => (el.id === selected ? { ...el, ...patch } : el)),
    );
  };

  const deleteSelected = useCallback(() => {
    if (!selected) return;
    setElements((prev) => prev.filter((el) => el.id !== selected));
    setSelected(null);
  }, [selected]);

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selected) return;
    const reader = new FileReader();
    reader.onload = () => {
      updateSelected({ imageSrc: reader.result as string });
    };
    reader.readAsDataURL(file);
  };

  const handleBgImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setBackground((prev) => ({
        ...prev,
        type: 'image',
        imageUrl: reader.result as string,
      }));
    };
    reader.readAsDataURL(file);
  };

  // ── Keyboard: Delete/Backspace removes selected element ──
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
        // Don't delete if user is typing in an input
        const tag = (e.target as HTMLElement)?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        e.preventDefault();
        deleteSelected();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [selected, deleteSelected]);

  // ── Export to HTML + CSS ──
  const exportTemplate = () => {
    const { html, css } = generateTemplateCode(elements, background, templateType);
    onSave({ html_template: html, css, elements, background });
  };

  // ── Background style ──
  const bgStyle = useMemo(() => {
    if (background.type === 'image' && background.imageUrl) {
      return {
        backgroundImage: `url(${background.imageUrl})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      };
    }
    if (background.type === 'gradient') {
      return {
        background: `linear-gradient(${background.gradientAngle}deg, ${background.color1}, ${background.color2})`,
      };
    }
    return { background: background.color1 };
  }, [background]);

  // ── Render ──
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-100 rounded-xl shadow-2xl w-[95vw] max-w-[1200px] h-[90vh] flex flex-col">
        {/* ═══ Header ═══ */}
        <div className="flex items-center justify-between px-5 py-3 bg-white rounded-t-xl border-b">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-gray-900">铭牌设计器</h2>
            <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
              {size.label}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowPreview(!showPreview)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border rounded-lg hover:bg-gray-50"
            >
              <Eye size={15} /> {showPreview ? '编辑' : '预览'}
            </button>
            <button
              onClick={exportTemplate}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
            >
              <Save size={15} /> 保存模板
            </button>
            <button onClick={onCancel} className="p-1.5 hover:bg-gray-100 rounded-lg">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* ═══ Body ═══ */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* ── Left: Element palette ── */}
          <div className="w-52 bg-white border-r overflow-y-auto p-3 space-y-3 flex-shrink-0">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              添加元素
            </div>
            {ELEMENT_PRESETS.map((preset) => {
              const alreadyAdded = elements.some((e) => e.field === preset.field);
              return (
                <button
                  key={preset.field}
                  onClick={() => addElement(preset)}
                  disabled={alreadyAdded && preset.field !== 'logo'}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
                    alreadyAdded && preset.field !== 'logo'
                      ? 'opacity-40 cursor-not-allowed bg-gray-50'
                      : 'hover:bg-indigo-50 hover:text-indigo-700'
                  }`}
                >
                  <span className="text-gray-400">{ICON_MAP[preset.field] || <Plus size={13} />}</span>
                  {preset.label}
                  {alreadyAdded && preset.field !== 'logo' && (
                    <span className="ml-auto text-[10px] text-gray-400">已添加</span>
                  )}
                </button>
              );
            })}

            {/* Elements in canvas */}
            <div className="border-t pt-3 mt-3">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                画布元素
              </div>
              {elements.length === 0 && (
                <div className="text-xs text-gray-400 px-3 py-2">
                  点击上方添加元素
                </div>
              )}
              {elements.map((el) => (
                <div
                  key={el.id}
                  onClick={() => setSelected(el.id)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 rounded text-sm text-left transition-colors cursor-pointer group ${
                    selected === el.id
                      ? 'bg-indigo-100 text-indigo-700'
                      : 'hover:bg-gray-50'
                  }`}
                >
                  <span className="text-gray-400">{ICON_MAP[el.field] || <Move size={13} />}</span>
                  <span className="flex-1">{el.label}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setElements((prev) => prev.filter((x) => x.id !== el.id));
                      if (selected === el.id) setSelected(null);
                    }}
                    className="p-0.5 rounded text-gray-300 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all"
                    title="删除"
                  >
                    <X size={13} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* ── Center: Canvas ── */}
          <div className="flex-1 flex items-center justify-center bg-gray-200/60 p-6 overflow-auto">
            <div
              ref={canvasRef}
              className="relative shadow-2xl rounded-lg overflow-hidden cursor-crosshair"
              style={{ width: canvasW, height: canvasH, ...bgStyle }}
              onClick={() => setSelected(null)}
            >
              {elements.map((el) => (
                <div
                  key={el.id}
                  onMouseDown={(e) => handleMouseDown(e, el.id)}
                  onClick={(e) => { e.stopPropagation(); setSelected(el.id); }}
                  className={`absolute cursor-move select-none ${
                    selected === el.id
                      ? 'ring-2 ring-blue-400 ring-offset-1'
                      : 'hover:ring-1 hover:ring-blue-300'
                  }`}
                  style={{
                    left: el.x,
                    top: el.y,
                    width: el.width,
                    height: el.height,
                  }}
                >
                  {el.type === 'text' && (
                    <div
                      style={{
                        fontSize: el.fontSize,
                        fontWeight: el.fontWeight,
                        color: el.color,
                        textAlign: el.textAlign,
                        lineHeight: `${el.height}px`,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                      }}
                    >
                      {el.field === 'role_label' ? (
                        <span
                          style={{
                            background: 'rgba(255,255,255,0.2)',
                            padding: '2px 8px',
                            borderRadius: 8,
                            fontSize: el.fontSize,
                            fontWeight: el.fontWeight,
                          }}
                        >
                          {SAMPLE[el.field as keyof typeof SAMPLE] || el.label}
                        </span>
                      ) : (
                        SAMPLE[el.field as keyof typeof SAMPLE] || el.label
                      )}
                    </div>
                  )}
                  {el.type === 'image' && (
                    <div className="w-full h-full flex items-center justify-center bg-white/10 rounded">
                      {el.imageSrc ? (
                        <img src={el.imageSrc} className="w-full h-full object-contain" alt="logo" />
                      ) : (
                        <div className="text-white/40 text-xs text-center">
                          <Image size={20} className="mx-auto mb-1" />
                          上传Logo
                        </div>
                      )}
                    </div>
                  )}
                  {el.type === 'qr' && (
                    <div className="w-full h-full flex items-center justify-center bg-white rounded">
                      <QrCode size={Math.min(el.width, el.height) * 0.7} className="text-gray-700" />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* ── Right: Properties panel ── */}
          <div className="w-64 bg-white border-l overflow-y-auto p-4 space-y-4 flex-shrink-0">
            {selectedEl ? (
              <>
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-gray-900">{selectedEl.label}</h3>
                  <button
                    onClick={deleteSelected}
                    className="p-1 text-red-400 hover:text-red-600 hover:bg-red-50 rounded"
                    title="删除元素"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>

                {/* Position */}
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">位置</div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-gray-500">
                      X
                      <input
                        type="number"
                        value={selectedEl.x}
                        onChange={(e) => updateSelected({ x: +e.target.value })}
                        className="w-full mt-0.5 px-2 py-1 border rounded text-sm"
                      />
                    </label>
                    <label className="text-xs text-gray-500">
                      Y
                      <input
                        type="number"
                        value={selectedEl.y}
                        onChange={(e) => updateSelected({ y: +e.target.value })}
                        className="w-full mt-0.5 px-2 py-1 border rounded text-sm"
                      />
                    </label>
                  </div>
                </div>

                {/* Size */}
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">尺寸</div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-xs text-gray-500">
                      宽
                      <input
                        type="number"
                        value={selectedEl.width}
                        onChange={(e) => updateSelected({ width: +e.target.value })}
                        className="w-full mt-0.5 px-2 py-1 border rounded text-sm"
                      />
                    </label>
                    <label className="text-xs text-gray-500">
                      高
                      <input
                        type="number"
                        value={selectedEl.height}
                        onChange={(e) => updateSelected({ height: +e.target.value })}
                        className="w-full mt-0.5 px-2 py-1 border rounded text-sm"
                      />
                    </label>
                  </div>
                </div>

                {/* Text properties */}
                {selectedEl.type === 'text' && (
                  <>
                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">字体</div>
                      <div className="grid grid-cols-2 gap-2">
                        <label className="text-xs text-gray-500">
                          大小
                          <input
                            type="number"
                            value={selectedEl.fontSize}
                            onChange={(e) => updateSelected({ fontSize: +e.target.value })}
                            className="w-full mt-0.5 px-2 py-1 border rounded text-sm"
                            min={6}
                            max={72}
                          />
                        </label>
                        <label className="text-xs text-gray-500">
                          粗细
                          <select
                            value={selectedEl.fontWeight}
                            onChange={(e) => updateSelected({ fontWeight: e.target.value })}
                            className="w-full mt-0.5 px-2 py-1 border rounded text-sm"
                          >
                            <option value="300">细体</option>
                            <option value="400">常规</option>
                            <option value="600">半粗</option>
                            <option value="700">粗体</option>
                            <option value="900">黑体</option>
                          </select>
                        </label>
                      </div>
                    </div>

                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">颜色</div>
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={selectedEl.color.replace(/[a-f0-9]{2}$/i, '') || selectedEl.color}
                          onChange={(e) => updateSelected({ color: e.target.value })}
                          className="w-8 h-8 rounded border cursor-pointer"
                        />
                        <input
                          type="text"
                          value={selectedEl.color}
                          onChange={(e) => updateSelected({ color: e.target.value })}
                          className="flex-1 px-2 py-1 border rounded text-sm font-mono"
                        />
                      </div>
                    </div>

                    <div>
                      <div className="text-xs font-medium text-gray-500 mb-1">对齐</div>
                      <div className="flex rounded-lg border overflow-hidden">
                        {(['left', 'center', 'right'] as const).map((a) => (
                          <button
                            key={a}
                            onClick={() => updateSelected({ textAlign: a })}
                            className={`flex-1 py-1.5 text-xs font-medium ${
                              selectedEl.textAlign === a
                                ? 'bg-indigo-600 text-white'
                                : 'text-gray-600 hover:bg-gray-50'
                            }`}
                          >
                            {a === 'left' ? '左' : a === 'center' ? '居中' : '右'}
                          </button>
                        ))}
                      </div>
                    </div>
                  </>
                )}

                {/* Image upload for logo */}
                {selectedEl.type === 'image' && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">图片</div>
                    <label className="flex items-center gap-2 px-3 py-2 border-2 border-dashed rounded-lg cursor-pointer hover:bg-gray-50 text-sm text-gray-500">
                      <Upload size={15} />
                      {selectedEl.imageSrc ? '更换图片' : '上传图片'}
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleImageUpload}
                        className="hidden"
                      />
                    </label>
                    {selectedEl.imageSrc && (
                      <img
                        src={selectedEl.imageSrc}
                        className="mt-2 w-full h-16 object-contain bg-gray-50 rounded"
                        alt="preview"
                      />
                    )}
                  </div>
                )}
              </>
            ) : (
              /* Background settings when nothing selected */
              <>
                <h3 className="text-sm font-bold text-gray-900">背景设置</h3>

                <div>
                  <div className="text-xs font-medium text-gray-500 mb-1">类型</div>
                  <div className="flex rounded-lg border overflow-hidden">
                    {(['solid', 'gradient', 'image'] as const).map((t) => (
                      <button
                        key={t}
                        onClick={() => setBackground((prev) => ({ ...prev, type: t }))}
                        className={`flex-1 py-1.5 text-xs font-medium ${
                          background.type === t
                            ? 'bg-indigo-600 text-white'
                            : 'text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        {t === 'solid' ? '纯色' : t === 'gradient' ? '渐变' : '图片'}
                      </button>
                    ))}
                  </div>
                </div>

                {background.type !== 'image' && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">
                      {background.type === 'solid' ? '颜色' : '渐变色'}
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="color"
                          value={background.color1}
                          onChange={(e) =>
                            setBackground((prev) => ({ ...prev, color1: e.target.value }))
                          }
                          className="w-8 h-8 rounded border cursor-pointer"
                        />
                        <input
                          type="text"
                          value={background.color1}
                          onChange={(e) =>
                            setBackground((prev) => ({ ...prev, color1: e.target.value }))
                          }
                          className="flex-1 px-2 py-1 border rounded text-sm font-mono"
                        />
                      </div>
                      {background.type === 'gradient' && (
                        <>
                          <div className="flex items-center gap-2">
                            <input
                              type="color"
                              value={background.color2}
                              onChange={(e) =>
                                setBackground((prev) => ({ ...prev, color2: e.target.value }))
                              }
                              className="w-8 h-8 rounded border cursor-pointer"
                            />
                            <input
                              type="text"
                              value={background.color2}
                              onChange={(e) =>
                                setBackground((prev) => ({ ...prev, color2: e.target.value }))
                              }
                              className="flex-1 px-2 py-1 border rounded text-sm font-mono"
                            />
                          </div>
                          <label className="text-xs text-gray-500">
                            角度 ({background.gradientAngle}°)
                            <input
                              type="range"
                              min={0}
                              max={360}
                              value={background.gradientAngle}
                              onChange={(e) =>
                                setBackground((prev) => ({
                                  ...prev,
                                  gradientAngle: +e.target.value,
                                }))
                              }
                              className="w-full mt-1"
                            />
                          </label>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {background.type === 'image' && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">背景图</div>
                    <label className="flex items-center gap-2 px-3 py-2 border-2 border-dashed rounded-lg cursor-pointer hover:bg-gray-50 text-sm text-gray-500">
                      <Upload size={15} />
                      {background.imageUrl ? '更换背景' : '上传背景图'}
                      <input
                        type="file"
                        accept="image/*"
                        onChange={handleBgImageUpload}
                        className="hidden"
                      />
                    </label>
                    {background.imageUrl && (
                      <img
                        src={background.imageUrl}
                        className="mt-2 w-full h-20 object-cover rounded"
                        alt="bg"
                      />
                    )}
                  </div>
                )}

                <div className="border-t pt-3">
                  <button
                    onClick={() => {
                      setElements(getDefaultElements(templateType));
                      setSelected(null);
                    }}
                    className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700"
                  >
                    <RotateCcw size={14} /> 重置为默认布局
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Default element layouts                                             */
/* ------------------------------------------------------------------ */

function getDefaultElements(type: 'badge' | 'tent_card'): DesignElement[] {
  const s = BADGE_SIZES[type];
  const w = s.w * SCALE;
  const h = s.h * SCALE;

  if (type === 'tent_card') {
    return [
      {
        id: nextId(), type: 'text', field: 'name', label: '姓名',
        x: (w - 300) / 2, y: h * 0.3, width: 300, height: 50,
        fontSize: 32, fontWeight: '700', color: '#ffffff',
        textAlign: 'center', isStatic: false,
      },
      {
        id: nextId(), type: 'text', field: 'title', label: '职位',
        x: (w - 240) / 2, y: h * 0.3 + 55, width: 240, height: 30,
        fontSize: 14, fontWeight: '400', color: '#ffffffcc',
        textAlign: 'center', isStatic: false,
      },
      {
        id: nextId(), type: 'text', field: 'organization', label: '单位',
        x: (w - 240) / 2, y: h * 0.3 + 85, width: 240, height: 28,
        fontSize: 13, fontWeight: '400', color: '#ffffffbb',
        textAlign: 'center', isStatic: false,
      },
    ];
  }

  // Badge default
  return [
    {
      id: nextId(), type: 'text', field: 'event_name', label: '活动名称',
      x: (w - 200) / 2, y: 12, width: 200, height: 24,
      fontSize: 10, fontWeight: '600', color: '#ffffffdd',
      textAlign: 'center', isStatic: true,
    },
    {
      id: nextId(), type: 'text', field: 'name', label: '姓名',
      x: (w - 200) / 2, y: h * 0.35, width: 200, height: 40,
      fontSize: 20, fontWeight: '700', color: '#ffffff',
      textAlign: 'center', isStatic: false,
    },
    {
      id: nextId(), type: 'text', field: 'title', label: '职位',
      x: (w - 160) / 2, y: h * 0.35 + 42, width: 160, height: 22,
      fontSize: 10, fontWeight: '400', color: '#ffffffcc',
      textAlign: 'center', isStatic: false,
    },
    {
      id: nextId(), type: 'text', field: 'organization', label: '单位',
      x: (w - 160) / 2, y: h * 0.35 + 64, width: 160, height: 20,
      fontSize: 9, fontWeight: '400', color: '#ffffffbb',
      textAlign: 'center', isStatic: false,
    },
    {
      id: nextId(), type: 'text', field: 'role_label', label: '角色标签',
      x: 15, y: h - 28, width: 80, height: 22,
      fontSize: 8, fontWeight: '600', color: '#ffffff',
      textAlign: 'center', isStatic: false,
    },
  ];
}

/* ------------------------------------------------------------------ */
/* Template code generation                                            */
/* ------------------------------------------------------------------ */

function generateTemplateCode(
  elements: DesignElement[],
  bg: BackgroundConfig,
  templateType: 'badge' | 'tent_card',
): { html: string; css: string } {
  const s = BADGE_SIZES[templateType];

  // Build background CSS
  let bgCss: string;
  if (bg.type === 'image' && bg.imageUrl) {
    bgCss = `background-image: url("${bg.imageUrl}"); background-size: cover; background-position: center;`;
  } else if (bg.type === 'gradient') {
    bgCss = `background: linear-gradient(${bg.gradientAngle}deg, ${bg.color1}, ${bg.color2});`;
  } else {
    bgCss = `background: ${bg.color1};`;
  }

  const fontStack =
    '"Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC", ' +
    '"Droid Sans Fallback", "PingFang SC", "Microsoft YaHei", ' +
    '"Helvetica Neue", sans-serif';

  // CSS
  const css = `@page { size: ${s.w}mm ${s.h}mm; margin: 0; }
body { margin: 0; padding: 0; font-family: ${fontStack}; }
.badge { width: ${s.w}mm; height: ${s.h}mm; position: relative; page-break-after: always; box-sizing: border-box; ${bgCss} overflow: hidden; }
${elements
  .map(
    (el) => `.el-${el.field} { position: absolute; left: ${pxToMm(el.x)}mm; top: ${pxToMm(el.y)}mm; width: ${pxToMm(el.width)}mm; height: ${pxToMm(el.height)}mm;${
      el.type === 'text'
        ? ` font-size: ${el.fontSize}pt; font-weight: ${el.fontWeight}; color: ${el.color}; text-align: ${el.textAlign}; line-height: ${pxToMm(el.height)}mm; white-space: nowrap; overflow: hidden;`
        : ''
    }${el.type === 'qr' ? ' background: #fff; border-radius: 2mm; display: flex; align-items: center; justify-content: center;' : ''} }`,
  )
  .join('\n')}
.role-tag-inner { background: rgba(255,255,255,0.2); padding: 1mm 2.5mm; border-radius: 2mm; }
.qr-img { width: 100%; height: 100%; object-fit: contain; padding: 1mm; }
.logo-img { width: 100%; height: 100%; object-fit: contain; }`;

  // HTML — Jinja2 template
  const bodyParts = elements
    .map((el) => {
      if (el.type === 'text') {
        if (el.field === 'role_label') {
          return `  <div class="el-${el.field}"><span class="role-tag-inner" style="background:{{ attendee.role_color }};color:{{ attendee.role_text }}">{{ attendee.role_label }}</span></div>`;
        }
        if (el.isStatic) {
          return `  <div class="el-${el.field}">{{ ${el.field} }}</div>`;
        }
        const jinja = `attendee.${el.field}`;
        return `  {% if ${jinja} %}<div class="el-${el.field}">{{ ${jinja} }}</div>{% endif %}`;
      }
      if (el.type === 'qr') {
        return `  {% if attendee.qr_data %}<div class="el-${el.field}"><img class="qr-img" src="{{ attendee.qr_data }}" alt="QR"></div>{% endif %}`;
      }
      if (el.type === 'image' && el.imageSrc) {
        return `  <div class="el-${el.field}"><img class="logo-img" src="${el.imageSrc}" alt="logo"></div>`;
      }
      return '';
    })
    .filter(Boolean)
    .join('\n');

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
{{ css }}
</style>
</head>
<body>
{% for attendee in attendees %}
<div class="badge">
${bodyParts}
</div>
{% endfor %}
</body>
</html>`;

  return { html, css };
}

function pxToMm(px: number): string {
  return (px / SCALE).toFixed(1);
}
