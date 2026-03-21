/**
 * EventDetailPage — Complete event management hub.
 *
 * Tabs:
 *   概览 | 参会人 | 座位图 | 铭牌 | 签到 | 文件 | 导入/导出 | 设置
 *
 * Each domain tab has an embedded sub-agent sidebar for AI assistance.
 * The floating global agent is still available via Layout.
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft, LayoutDashboard, Users, Grid3X3, Tag,
  QrCode, FolderOpen, ArrowDownUp, Settings
} from 'lucide-react';
import { apiClient } from '../lib/api';
import { OverviewTab } from '../components/tabs/OverviewTab';
import { AttendeesTab } from '../components/tabs/AttendeesTab';
import { SeatingTab } from '../components/tabs/SeatingTab';
import { BadgeTab } from '../components/tabs/BadgeTab';
import { CheckinDesignTab } from '../components/tabs/CheckinDesignTab';
import { FilesTab } from '../components/tabs/FilesTab';
import { ImportTab } from '../components/tabs/ImportTab';
import { SettingsTab } from '../components/tabs/SettingsTab';

const STATUS_BADGE: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'bg-yellow-100 text-yellow-800' },
  active: { label: '进行中', color: 'bg-green-100 text-green-800' },
  completed: { label: '已完成', color: 'bg-gray-100 text-gray-800' },
  cancelled: { label: '已取消', color: 'bg-red-100 text-red-800' },
};

export function EventDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('overview');

  const { data: event, isLoading } = useQuery({
    queryKey: ['event', id],
    queryFn: () => apiClient.getEvent(id!),
    enabled: !!id,
  }) as any;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">加载中...</div>
      </div>
    );
  }

  if (!event) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <div className="text-gray-500 text-lg">活动不存在</div>
        <button onClick={() => navigate('/')}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">
          返回列表
        </button>
      </div>
    );
  }

  const status = STATUS_BADGE[(event as any).status] || STATUS_BADGE.draft;

  const tabs = [
    { id: 'overview', label: '概览', icon: LayoutDashboard },
    { id: 'attendees', label: '参会人', icon: Users },
    { id: 'seating', label: '座位图', icon: Grid3X3 },
    { id: 'badge', label: '铭牌', icon: Tag },
    { id: 'checkin', label: '签到', icon: QrCode },
    { id: 'files', label: '文件', icon: FolderOpen },
    { id: 'import', label: '导入/导出', icon: ArrowDownUp },
    { id: 'settings', label: '设置', icon: Settings },
  ];

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-4">
      {/* Header */}
      <div className="flex items-center gap-4 flex-shrink-0">
        <button onClick={() => navigate('/')}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
          <ArrowLeft size={22} className="text-gray-600" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900 truncate">
              {(event as any).name}
            </h1>
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${status.color}`}>
              {status.label}
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            {(event as any).event_date && new Date((event as any).event_date).toLocaleDateString('zh-CN')}
            {(event as any).location && ` · ${(event as any).location}`}
            {(event as any).layout_type && ` · ${(event as any).layout_type}`}
            {(event as any).venue_rows > 0 && ` · ${(event as any).venue_rows}×${(event as any).venue_cols}座`}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 flex-shrink-0">
        <div className="flex gap-1 overflow-x-auto">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                  isActive
                    ? 'border-indigo-600 text-indigo-600'
                    : 'border-transparent text-gray-500 hover:text-gray-800'
                }`}
              >
                <Icon size={16} />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tab Content — all tabs stay mounted, hidden via CSS to preserve state */}
      {/* Uses absolute positioning so height is guaranteed regardless of flex resolution */}
      <div className="flex-1 min-h-0 relative">
        <div className={activeTab === 'overview' ? 'absolute inset-0 overflow-auto' : 'hidden'}><OverviewTab eventId={id!} /></div>
        <div className={activeTab === 'attendees' ? 'absolute inset-0 overflow-auto' : 'hidden'}><AttendeesTab eventId={id!} /></div>
        <div className={activeTab === 'seating' ? 'absolute inset-0' : 'hidden'}><SeatingTab eventId={id!} event={event as any} /></div>
        <div className={activeTab === 'badge' ? 'absolute inset-0 overflow-auto' : 'hidden'}><BadgeTab eventId={id!} /></div>
        <div className={activeTab === 'checkin' ? 'absolute inset-0 overflow-auto' : 'hidden'}><CheckinDesignTab eventId={id!} /></div>
        <div className={activeTab === 'files' ? 'absolute inset-0 overflow-auto' : 'hidden'}><FilesTab eventId={id!} /></div>
        <div className={activeTab === 'import' ? 'absolute inset-0 overflow-auto' : 'hidden'}><ImportTab eventId={id!} /></div>
        <div className={activeTab === 'settings' ? 'absolute inset-0 overflow-auto' : 'hidden'}><SettingsTab eventId={id!} event={event as any} /></div>
      </div>
    </div>
  );
}
