/**
 * CheckinDesignTab — Check-in page design + preview + QR code.
 *
 * Left: phone preview (iframe), stats, QR code, link
 * Right: sub-agent for AI-driven design
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  QrCode, Smartphone, Users, CheckCircle,
  ExternalLink, Copy, RefreshCw,
} from 'lucide-react';
import { apiClient } from '../../lib/api';
import { SubAgentPanel } from '../SubAgentPanel';

interface CheckinDesignTabProps {
  eventId: string;
}

interface DashboardStats {
  total_attendees: number;
  checked_in_count: number;
  checkin_rate: number;
}

const API_BASE = import.meta.env.VITE_API_BASE || '';

export function CheckinDesignTab({ eventId }: CheckinDesignTabProps) {
  const [copied, setCopied] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);

  const checkinUrl = `${window.location.origin}/p/${eventId}/checkin`;
  const iframeSrc = `/p/${eventId}/checkin`;

  const { data: stats } = useQuery({
    queryKey: ['dashboard', eventId],
    queryFn: () => apiClient.getDashboard(eventId) as Promise<DashboardStats>,
    refetchInterval: 10000,
  });

  const copyLink = () => {
    navigator.clipboard.writeText(checkinUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="flex h-full">
      {/* ═══ Left: Preview + Controls ═══ */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-w-0">
        {/* Live Stats */}
        {stats && (
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-white rounded-lg border border-gray-200 p-3 text-center">
              <Users size={18} className="mx-auto text-indigo-500 mb-1" />
              <p className="text-xl font-bold text-gray-900">{stats.total_attendees}</p>
              <p className="text-[10px] text-gray-500">总人数</p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-3 text-center">
              <CheckCircle size={18} className="mx-auto text-green-500 mb-1" />
              <p className="text-xl font-bold text-green-600">{stats.checked_in_count}</p>
              <p className="text-[10px] text-gray-500">已签到</p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-3 text-center">
              <div className="w-[18px] h-[18px] mx-auto mb-1 rounded-full bg-blue-100 flex items-center justify-center text-[10px] font-bold text-blue-600">%</div>
              <p className="text-xl font-bold text-blue-600">
                {stats.checkin_rate != null
                  ? `${(stats.checkin_rate * 100).toFixed(0)}%`
                  : '0%'}
              </p>
              <p className="text-[10px] text-gray-500">签到率</p>
            </div>
          </div>
        )}

        {/* Check-in link + actions */}
        <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-3">
          <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <QrCode size={16} className="text-indigo-600" />
            签到链接
          </h3>
          <div className="flex items-center gap-2">
            <div className="flex-1 px-3 py-2 bg-gray-50 border rounded-lg text-xs text-gray-600 font-mono truncate">
              {checkinUrl}
            </div>
            <button onClick={copyLink}
              className="shrink-0 flex items-center gap-1 px-3 py-2 border rounded-lg text-xs text-gray-600 hover:bg-gray-50"
            >
              <Copy size={12} />
              {copied ? '已复制' : '复制'}
            </button>
            <a href={iframeSrc} target="_blank" rel="noopener noreferrer"
              className="shrink-0 flex items-center gap-1 px-3 py-2 border rounded-lg text-xs text-indigo-600 hover:bg-indigo-50"
            >
              <ExternalLink size={12} />
              打开
            </a>
          </div>
          <p className="text-[10px] text-gray-400">
            参会者扫码打开此链接 → 输入姓名 → 完成签到。可将此链接生成二维码打印。
          </p>
        </div>

        {/* Phone preview */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Smartphone size={16} className="text-indigo-600" />
              签到页预览
            </h3>
            <button onClick={() => setPreviewKey((k) => k + 1)}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-indigo-600"
            >
              <RefreshCw size={12} />
              刷新
            </button>
          </div>

          {/* Phone frame with iframe */}
          <div className="mx-auto" style={{ width: '260px' }}>
            <div className="bg-gray-900 rounded-[28px] p-[6px] shadow-xl">
              {/* Notch */}
              <div className="bg-gray-900 mx-auto w-20 h-5 rounded-b-xl flex items-center justify-center relative z-10">
                <div className="w-12 h-1.5 bg-gray-700 rounded-full" />
              </div>
              {/* Screen */}
              <div className="bg-white rounded-[22px] overflow-hidden" style={{ height: '460px', marginTop: '-8px' }}>
                <iframe
                  key={previewKey}
                  src={iframeSrc}
                  className="w-full h-full border-0"
                  title="签到页预览"
                  style={{ transform: 'scale(1)', transformOrigin: 'top left' }}
                />
              </div>
              {/* Home indicator */}
              <div className="flex justify-center py-2">
                <div className="w-20 h-1 bg-gray-600 rounded-full" />
              </div>
            </div>
          </div>

          <p className="text-[10px] text-gray-400 text-center mt-3">
            这是参会者手机上看到的签到页面。让 AI 助手帮你自定义风格。
          </p>
        </div>
      </div>

      {/* ═══ Right: AI Assistant ═══ */}
      <SubAgentPanel
        eventId={eventId}
        scope="pagegen"
        title="签到页设计助手"
        placeholder="如：生成签到页、设计深蓝风格签到页、生成签到二维码..."
        welcomeMessage={`我可以帮你：
1. 生成签到页 — 参会者扫码即可在手机上签到
2. 自定义设计 — 上传参考图片，我来设计签到页风格
3. 生成二维码 — 生成签到入口二维码供打印
4. 查看签到统计 — 实时签到人数和签到率

签到链接已就绪：${checkinUrl}
参会者打开后输入姓名即可签到。

需要我帮你做什么？`}
      />
    </div>
  );
}
