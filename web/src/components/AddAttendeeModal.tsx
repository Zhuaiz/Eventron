import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { apiClient } from '../lib/api';

interface AddAttendeeModalProps {
  eventId: string;
  isOpen: boolean;
  onClose: () => void;
}

const ROLE_PRESETS = [
  '参会者', '甲方嘉宾', '演讲嘉宾', '合作伙伴', '媒体',
  '工作人员', '组织方', '投资人', '客户代表',
];

const PRIORITY_PRESETS: { label: string; value: number }[] = [
  { label: '普通 (0)', value: 0 },
  { label: '工作人员 (1)', value: 1 },
  { label: '嘉宾 (5)', value: 5 },
  { label: '重要嘉宾 (10)', value: 10 },
  { label: '贵宾 (15)', value: 15 },
  { label: '最高优先 (20)', value: 20 },
];

export function AddAttendeeModal({ eventId, isOpen, onClose }: AddAttendeeModalProps) {
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [organization, setOrganization] = useState('');
  const [role, setRole] = useState('参会者');
  const [customRole, setCustomRole] = useState('');
  const [priority, setPriority] = useState(0);
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');

  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: async () => {
      const finalRole = role === '__custom__' ? customRole : role;
      return apiClient.createAttendee(eventId, {
        name,
        title: title || undefined,
        organization: organization || undefined,
        role: finalRole,
        priority,
        phone: phone || undefined,
        email: email || undefined,
      } as any);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attendees'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      onClose();
      resetForm();
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : '添加失败');
    },
  });

  const resetForm = () => {
    setName('');
    setTitle('');
    setOrganization('');
    setRole('参会者');
    setCustomRole('');
    setPriority(0);
    setPhone('');
    setEmail('');
    setError('');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) {
      setError('请填写参会人姓名');
      return;
    }
    if (role === '__custom__' && !customRole.trim()) {
      setError('请填写自定义角色');
      return;
    }
    createMutation.mutate();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-lg max-w-md w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200">
          <h2 className="text-xl font-bold text-gray-900">添加参会人</h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 rounded transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              姓名 *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="输入参会人姓名"
            />
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              职位
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="输入职位"
            />
          </div>

          {/* Organization */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              组织/公司
            </label>
            <input
              type="text"
              value={organization}
              onChange={(e) => setOrganization(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="输入组织或公司名"
            />
          </div>

          {/* Role — free-text with presets */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              角色标签
            </label>
            <select
              value={ROLE_PRESETS.includes(role) ? role : '__custom__'}
              onChange={(e) => {
                setRole(e.target.value);
                if (e.target.value !== '__custom__') setCustomRole('');
              }}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {ROLE_PRESETS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
              <option value="__custom__">自定义...</option>
            </select>
            {(role === '__custom__' || !ROLE_PRESETS.includes(role)) && (
              <input
                type="text"
                value={customRole}
                onChange={(e) => setCustomRole(e.target.value)}
                className="w-full mt-2 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                placeholder="输入自定义角色名称"
              />
            )}
          </div>

          {/* Priority */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              优先级
              <span className="ml-2 text-xs text-gray-400">
                (数字越大 = 座位越靠前)
              </span>
            </label>
            <div className="flex items-center gap-3">
              <select
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {PRIORITY_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
              <input
                type="number"
                min={0}
                max={100}
                value={priority}
                onChange={(e) => setPriority(Math.min(100, Math.max(0, Number(e.target.value))))}
                className="w-20 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 text-center"
              />
            </div>
          </div>

          {/* Phone */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              电话
            </label>
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="输入电话号码"
            />
          </div>

          {/* Email */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              邮箱
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="输入邮箱地址"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 font-medium hover:bg-gray-50 transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="flex-1 px-4 py-2 bg-indigo-600 text-white font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {createMutation.isPending ? '添加中...' : '添加'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
