import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Check, Download } from 'lucide-react';
import { apiClient } from '../../lib/api';
import { AddAttendeeModal } from '../AddAttendeeModal';

interface AttendeesTabProps {
  eventId: string;
}

// Priority-based role badge colors (role is now free-text)
function getRoleBadgeColor(priority: number): string {
  if (priority >= 10) return 'bg-purple-100 text-purple-800';
  if (priority >= 5) return 'bg-orange-100 text-orange-800';
  if (priority >= 1) return 'bg-blue-100 text-blue-800';
  return 'bg-gray-100 text-gray-800';
}

const STATUS_LABELS = {
  pending: { label: '待确认', color: 'bg-yellow-100 text-yellow-800' },
  confirmed: { label: '已确认', color: 'bg-green-100 text-green-800' },
  checked_in: { label: '已签到', color: 'bg-blue-100 text-blue-800' },
  absent: { label: '缺席', color: 'bg-gray-100 text-gray-800' },
  cancelled: { label: '已取消', color: 'bg-red-100 text-red-800' },
};

export function AttendeesTab({ eventId }: AttendeesTabProps) {
  const [showAddModal, setShowAddModal] = useState(false);
  const [roleFilter, setRoleFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const queryClient = useQueryClient();

  const { data: attendees = [], isLoading } = useQuery({
    queryKey: ['attendees', eventId, roleFilter, statusFilter],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (roleFilter) params.role = roleFilter;
      if (statusFilter) params.status = statusFilter;
      const result = await apiClient.getAttendees(eventId, params);
      return (result as any).data || result;
    },
  });

  const checkinMutation = useMutation({
    mutationFn: (attendeeId: string) =>
      apiClient.checkinAttendee(eventId, attendeeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attendees'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (attendeeId: string) =>
      apiClient.deleteAttendee(eventId, attendeeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attendees'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const handleCheckin = (attendeeId: string) => {
    checkinMutation.mutate(attendeeId);
  };

  const handleDelete = (attendeeId: string, name: string) => {
    if (confirm(`确定要删除参会者 "${name}" 吗？`)) {
      deleteMutation.mutate(attendeeId);
    }
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col lg:flex-row gap-4 items-start lg:items-center justify-between">
        <div className="flex gap-2 flex-wrap">
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
          >
            <option value="">所有角色</option>
            <option value="attendee">参会者</option>
            <option value="vip">VIP</option>
            <option value="speaker">演讲者</option>
            <option value="organizer">组织者</option>
            <option value="staff">工作人员</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
          >
            <option value="">所有状态</option>
            <option value="pending">待确认</option>
            <option value="confirmed">已确认</option>
            <option value="checked_in">已签到</option>
            <option value="absent">缺席</option>
            <option value="cancelled">已取消</option>
          </select>
        </div>

        <div className="flex gap-2">
          <a
            href={apiClient.getExportAttendeesUrl(eventId)}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-medium whitespace-nowrap"
          >
            <Download size={18} />
            导出Excel
          </a>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium whitespace-nowrap"
          >
            <Plus size={18} />
            添加参会人
          </button>
        </div>
      </div>

      {/* Attendees Table */}
      <div className="bg-white rounded-lg shadow overflow-x-auto">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500">加载中...</div>
        ) : (attendees as any[]).length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            还没有参会人
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left text-sm font-semibold text-gray-900">
                  姓名
                </th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-gray-900">
                  职位/组织
                </th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-gray-900">
                  角色
                </th>
                <th className="px-6 py-3 text-left text-sm font-semibold text-gray-900">
                  状态
                </th>
                <th className="px-6 py-3 text-right text-sm font-semibold text-gray-900">
                  操作
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(attendees as any[]).map((attendee) => (
                <tr key={attendee.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 text-sm font-medium text-gray-900">
                    {attendee.name}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    <div>{attendee.title || '-'}</div>
                    <div className="text-xs text-gray-500">{attendee.organization || ''}</div>
                  </td>
                  <td className="px-6 py-4 text-sm">
                    <span
                      className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${
                        getRoleBadgeColor(attendee.priority ?? 0)
                      }`}
                    >
                      {attendee.role || '参会者'}
                      {(attendee.priority ?? 0) > 0 && (
                        <span className="ml-1 opacity-60">P{attendee.priority}</span>
                      )}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm">
                    <span
                      className={`inline-block px-2 py-1 rounded-full text-xs font-medium ${
                        STATUS_LABELS[
                          attendee.status as keyof typeof STATUS_LABELS
                        ]?.color || 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {STATUS_LABELS[
                        attendee.status as keyof typeof STATUS_LABELS
                      ]?.label || attendee.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-right">
                    <div className="flex items-center justify-end gap-2">
                      {attendee.status !== 'checked_in' && (
                        <button
                          onClick={() => handleCheckin(attendee.id)}
                          disabled={checkinMutation.isPending}
                          className="p-1 hover:bg-green-100 rounded transition-colors disabled:opacity-50"
                          title="签到"
                        >
                          <Check size={18} className="text-green-600" />
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(attendee.id, attendee.name)}
                        disabled={deleteMutation.isPending}
                        className="p-1 hover:bg-red-100 rounded transition-colors disabled:opacity-50"
                        title="删除"
                      >
                        <Trash2 size={18} className="text-red-600" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Add Attendee Modal */}
      <AddAttendeeModal
        eventId={eventId}
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
      />
    </div>
  );
}
