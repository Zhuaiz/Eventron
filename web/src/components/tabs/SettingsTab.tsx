import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertCircle } from 'lucide-react';
import { apiClient } from '../../lib/api';

interface SettingsTabProps {
  eventId: string;
  event: any;
}

export function SettingsTab({ eventId, event }: SettingsTabProps) {
  const [name, setName] = useState(event.name);
  const [eventDate, setEventDate] = useState(
    event.event_date ? event.event_date.split('T')[0] : ''
  );
  const [location, setLocation] = useState(event.location || '');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const updateMutation = useMutation({
    mutationFn: async () => {
      return apiClient.updateEvent(eventId, {
        name,
        event_date: eventDate,
        location,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['event', eventId] });
      setError('');
      setSuccess('更新成功');
      setTimeout(() => setSuccess(''), 3000);
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : '更新失败');
      setSuccess('');
    },
  });

  const activateMutation = useMutation({
    mutationFn: () => apiClient.activateEvent(eventId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['event', eventId] });
      setError('');
      setSuccess('活动已激活');
      setTimeout(() => setSuccess(''), 3000);
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : '激活失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => apiClient.deleteEvent(eventId),
    onSuccess: () => {
      navigate('/');
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : '删除失败');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) {
      setError('请填写活动名称');
      return;
    }
    updateMutation.mutate();
  };

  const handleActivate = () => {
    if (confirm('确定要激活此活动吗？激活后将无法编辑基本信息。')) {
      activateMutation.mutate();
    }
  };

  const handleDelete = () => {
    if (
      confirm(
        '确定要删除此活动吗？此操作不可撤销，将删除所有相关数据。'
      )
    ) {
      deleteMutation.mutate();
    }
  };

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Status */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">活动状态</h3>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-gray-600">当前状态</p>
            <p className="text-lg font-semibold text-gray-900 mt-1">
              {event.status === 'draft'
                ? '草稿'
                : event.status === 'active'
                ? '进行中'
                : event.status === 'completed'
                ? '已完成'
                : '已取消'}
            </p>
          </div>
          {event.status === 'draft' && (
            <button
              onClick={handleActivate}
              disabled={activateMutation.isPending}
              className="px-6 py-2 bg-green-600 text-white font-medium rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {activateMutation.isPending ? '激活中...' : '激活活动'}
            </button>
          )}
        </div>
      </div>

      {/* Basic Info */}
      <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-900">基本信息</h3>
        <p className="text-xs text-gray-500 -mt-2">
          座位布局、行列数请在「座位图」标签页中管理
        </p>

        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            活动名称
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={event.status !== 'draft'}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-500"
          />
        </div>

        {/* Event Date */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            活动日期
          </label>
          <input
            type="date"
            value={eventDate}
            onChange={(e) => setEventDate(e.target.value)}
            disabled={event.status !== 'draft'}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-500"
          />
        </div>

        {/* Location */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            活动地点
          </label>
          <input
            type="text"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            disabled={event.status !== 'draft'}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-500"
          />
        </div>

        {/* Messages */}
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}
        {success && (
          <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            {success}
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={updateMutation.isPending}
          className="w-full px-4 py-2 bg-indigo-600 text-white font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {updateMutation.isPending ? '保存中...' : '保存更改'}
        </button>
      </form>

      {/* Danger Zone */}
      {event.status === 'draft' && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <div className="flex gap-3 mb-4">
            <AlertCircle className="text-red-600 flex-shrink-0" size={20} />
            <div>
              <h3 className="font-semibold text-red-900">危险区域</h3>
              <p className="text-sm text-red-700 mt-1">这些操作无法撤销</p>
            </div>
          </div>
          <button
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="w-full px-4 py-2 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {deleteMutation.isPending ? '删除中...' : '删除活动'}
          </button>
        </div>
      )}
    </div>
  );
}
