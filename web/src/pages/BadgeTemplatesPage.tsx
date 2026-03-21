import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Edit, Eye, Tag, CreditCard, Award } from 'lucide-react';
import { apiClient } from '../lib/api';
import { BadgeTemplateModal } from '../components/BadgeTemplateModal';

interface BadgeTemplate {
  id: string;
  name: string;
  template_type: string;
  html_template: string;
  css: string;
  is_builtin: boolean;
  style_category?: string;
}

const TEMPLATE_TYPES = [
  { value: '', label: '全部类型' },
  { value: 'badge', label: '胸牌' },
  { value: 'tent_card', label: '桌签' },
];

/**
 * Built-in templates — iframe is rendered at native size then CSS-scaled
 * into a fixed thumbnail box.  `nativeW/H` = the real badge pixel size
 * the preview endpoint produces.
 */
const BUILTIN_PREVIEWS = [
  {
    name: '竖版会议胸牌',
    templateName: 'conference',
    type: 'badge',
    desc: '90×130mm · 深蓝渐变 + 城市天际线 + 白色姓名横条',
    icon: Award,
    nativeW: 340,
    nativeH: 492,
  },
  {
    name: '横版商务胸牌',
    templateName: 'business',
    type: 'badge',
    desc: '90×54mm · 深蓝渐变 + 白色姓名横条 + 金色装饰条',
    icon: Tag,
    nativeW: 340,
    nativeH: 204,
  },
  {
    name: '桌签',
    templateName: 'tent_card',
    type: 'tent_card',
    desc: '210×99mm · 渐变对折式桌签',
    icon: CreditCard,
    nativeW: 794,
    nativeH: 375,
  },
];

/** Compute a CSS scale so the native badge fits inside a target box. */
function fitScale(
  nativeW: number, nativeH: number,
  boxW: number, boxH: number,
) {
  return Math.min(boxW / nativeW, boxH / nativeH);
}

const THUMB_BOX_W = 220;
const THUMB_BOX_H = 180;

export function BadgeTemplatesPage() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState<BadgeTemplate | null>(null);
  const [templateTypeFilter, setTemplateTypeFilter] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewNative, setPreviewNative] = useState<{ w: number; h: number } | null>(null);
  const queryClient = useQueryClient();

  const { data: templates = [], isLoading } = useQuery({
    queryKey: ['badge-templates', templateTypeFilter],
    queryFn: async () => {
      const result = await apiClient.getBadgeTemplates(
        templateTypeFilter || undefined
      );
      return (result as any).data || result;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (templateId: string) =>
      apiClient.deleteBadgeTemplate(templateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['badge-templates'] });
    },
  });

  const handleDelete = (templateId: string, templateName: string) => {
    if (confirm(`确定要删除模板 "${templateName}" 吗？`)) {
      deleteMutation.mutate(templateId);
    }
  };

  const customTemplates = (templates as BadgeTemplate[]).filter(
    (t) => !t.is_builtin,
  );

  /* -- open full-size preview modal -- */
  const openPreview = (url: string, nW: number, nH: number) => {
    setPreviewUrl(url);
    setPreviewNative({ w: nW, h: nH });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">模板管理</h1>
          <p className="text-gray-600 mt-1">管理胸牌和桌签模板</p>
        </div>
        <button
          onClick={() => {
            setSelectedTemplate(null);
            setShowCreateModal(true);
          }}
          className="flex items-center gap-2 px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium"
        >
          <Plus size={20} />
          新建模板
        </button>
      </div>

      {/* Built-in Templates */}
      <div>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">内置模板</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {BUILTIN_PREVIEWS.map((bt) => {
            const Icon = bt.icon;
            const scale = fitScale(bt.nativeW, bt.nativeH, THUMB_BOX_W, THUMB_BOX_H);
            const thumbW = bt.nativeW * scale;
            const thumbH = bt.nativeH * scale;
            const url = apiClient.getTemplatePreviewUrl(bt.templateName);
            return (
              <div
                key={bt.templateName}
                className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow overflow-hidden"
              >
                {/* Scaled iframe thumbnail — no scrollbar */}
                <div
                  className="bg-gray-100 flex justify-center items-center cursor-pointer"
                  style={{ height: `${THUMB_BOX_H + 16}px` }}
                  onClick={() => openPreview(url, bt.nativeW, bt.nativeH)}
                >
                  <div style={{
                    width: `${thumbW}px`,
                    height: `${thumbH}px`,
                    overflow: 'hidden',
                    borderRadius: '4px',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.12)',
                  }}>
                    <iframe
                      src={url}
                      scrolling="no"
                      className="border-0 pointer-events-none"
                      style={{
                        width: `${bt.nativeW}px`,
                        height: `${bt.nativeH}px`,
                        transform: `scale(${scale})`,
                        transformOrigin: 'top left',
                      }}
                      title={bt.name}
                      tabIndex={-1}
                    />
                  </div>
                </div>

                <div className="p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Icon size={16} className="text-indigo-500" />
                    <h3 className="font-semibold text-gray-900">{bt.name}</h3>
                    <span className="ml-auto px-2 py-0.5 bg-blue-100 text-blue-800 text-[10px] font-medium rounded">
                      内置
                    </span>
                  </div>
                  <p className="text-xs text-gray-500">{bt.desc}</p>
                  <button
                    onClick={() => openPreview(url, bt.nativeW, bt.nativeH)}
                    className="mt-3 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm"
                  >
                    <Eye size={14} />
                    预览大图
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Custom Templates */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-800">自定义模板</h2>
          <select
            value={templateTypeFilter}
            onChange={(e) => setTemplateTypeFilter(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {TEMPLATE_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {isLoading ? (
            <div className="col-span-full text-center text-gray-500 py-8">
              加载中...
            </div>
          ) : customTemplates.length === 0 ? (
            <div className="col-span-full text-center text-gray-400 py-12">
              <Tag size={40} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">还没有自定义模板</p>
              <p className="text-xs mt-1">
                点击右上角「新建模板」或在活动的铭牌页面让 AI 帮你设计
              </p>
            </div>
          ) : (
            customTemplates.map((template) => {
              const custNativeW = 340;
              const custNativeH = template.template_type === 'tent_card' ? 375 : 492;
              const custScale = fitScale(custNativeW, custNativeH, THUMB_BOX_W, THUMB_BOX_H);
              const custThumbW = custNativeW * custScale;
              const custThumbH = custNativeH * custScale;
              const custUrl = apiClient.getTemplatePreviewUrl(
                template.template_type, template.id
              );
              return (
                <div
                  key={template.id}
                  className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow overflow-hidden"
                >
                  {/* Scaled iframe thumbnail */}
                  <div
                    className="bg-gray-100 flex justify-center items-center cursor-pointer"
                    style={{ height: `${THUMB_BOX_H + 16}px` }}
                    onClick={() => openPreview(custUrl, custNativeW, custNativeH)}
                  >
                    <div style={{
                      width: `${custThumbW}px`,
                      height: `${custThumbH}px`,
                      overflow: 'hidden',
                      borderRadius: '4px',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.12)',
                    }}>
                      <iframe
                        src={custUrl}
                        scrolling="no"
                        className="border-0 pointer-events-none"
                        style={{
                          width: `${custNativeW}px`,
                          height: `${custNativeH}px`,
                          transform: `scale(${custScale})`,
                          transformOrigin: 'top left',
                        }}
                        title={template.name}
                        tabIndex={-1}
                      />
                    </div>
                  </div>

                  {/* Info */}
                  <div className="p-4">
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div>
                        <h3 className="font-semibold text-gray-900">
                          {template.name}
                        </h3>
                        <p className="text-xs text-gray-500 mt-0.5">
                          {template.template_type === 'tent_card' ? '桌签' : '胸牌'}
                          {template.style_category ? ` · ${template.style_category}` : ''}
                        </p>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-2">
                      <button
                        onClick={() => openPreview(custUrl, custNativeW, custNativeH)}
                        className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm"
                      >
                        <Eye size={14} />
                        预览
                      </button>
                      <button
                        onClick={() => {
                          setSelectedTemplate(template);
                          setShowCreateModal(true);
                        }}
                        className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 text-sm"
                      >
                        <Edit size={14} />
                        编辑
                      </button>
                      <button
                        onClick={() =>
                          handleDelete(template.id, template.name)
                        }
                        disabled={deleteMutation.isPending}
                        className="flex items-center justify-center gap-1 px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 text-sm disabled:opacity-50"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Create/Edit Modal */}
      <BadgeTemplateModal
        isOpen={showCreateModal}
        template={selectedTemplate}
        onClose={() => setSelectedTemplate(null)}
        onModalClose={() => setShowCreateModal(false)}
      />

      {/* Full-size Preview Modal */}
      {previewUrl && previewNative && (
        <PreviewModal
          url={previewUrl}
          nativeW={previewNative.w}
          nativeH={previewNative.h}
          onClose={() => { setPreviewUrl(null); setPreviewNative(null); }}
        />
      )}
    </div>
  );
}

/* ───── Full-size preview modal ───── */

function PreviewModal({
  url, nativeW, nativeH, onClose,
}: {
  url: string; nativeW: number; nativeH: number; onClose: () => void;
}) {
  // Scale the badge to fit within the viewport with some padding
  const maxW = Math.min(window.innerWidth * 0.85, 700);
  const maxH = window.innerHeight * 0.78;
  const scale = fitScale(nativeW, nativeH, maxW, maxH);
  const dispW = nativeW * scale;
  const dispH = nativeH * scale;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl flex flex-col"
        style={{ width: `${dispW + 48}px` }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h3 className="text-sm font-semibold text-gray-900">模板预览</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>
        <div className="flex justify-center p-6 bg-gray-100">
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
              title="Template Preview"
            />
          </div>
        </div>
        <div className="flex justify-end px-4 py-3 border-t">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
