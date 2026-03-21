/**
 * AgentSettingsPage — Global settings for all AI agent plugins.
 *
 * Two sections:
 *   1. LLM 模型配置 — model names, API keys per tier
 *   2. Agent 插件配置 — prompts, model tier, enabled per plugin
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft, Bot, ChevronDown, ChevronRight, RotateCcw,
  Save, Zap, Brain, Sparkles, Crown, ToggleLeft, ToggleRight,
  Key, Eye, EyeOff, Server,
} from 'lucide-react';
import { apiClient } from '../lib/api';
import type { AgentConfig, AgentConfigDetail, LLMProviderInfo } from '../lib/api';

const TIER_META: Record<string, {
  label: string; icon: typeof Zap; color: string; bg: string;
}> = {
  fast:   { label: 'Fast',   icon: Zap,      color: 'text-green-600',  bg: 'bg-green-50' },
  smart:  { label: 'Smart',  icon: Brain,     color: 'text-blue-600',   bg: 'bg-blue-50' },
  strong: { label: 'Strong', icon: Sparkles,  color: 'text-purple-600', bg: 'bg-purple-50' },
  max:    { label: 'Max',    icon: Crown,     color: 'text-amber-600',  bg: 'bg-amber-50' },
};

const TIER_ORDER = ['fast', 'smart', 'strong', 'max'];

const PLUGIN_LABELS: Record<string, { zh: string; desc: string }> = {
  orchestrator: { zh: '路由器', desc: '分析用户意图，分发到对应子Agent' },
  identity: { zh: '身份识别', desc: '从对话中识别用户身份' },
  organizer: { zh: '活动管理', desc: '创建活动、规划座位、管理参会人' },
  seating: { zh: '座位管理', desc: '座位布局和分配（ReAct工具调用）' },
  change: { zh: '座位变更', desc: '处理换座、请假等变更请求' },
  planner: { zh: '规划助手', desc: '多模态输入分析、任务拆解' },
  pagegen: { zh: '签到页设计', desc: 'H5签到页 vibe coding 生成' },
  badge: { zh: '铭牌设计', desc: '铭牌模板设计和生成' },
  checkin: { zh: '签到', desc: '签到流程处理' },
  guide: { zh: '引导', desc: '座位引导和查询' },
};

// ── TierSelect component ──────────────────────────────────────

function TierSelect({ value, onChange, label }: {
  value: string; onChange: (v: string) => void; label?: string;
}) {
  return (
    <div>
      {label && <label className="block text-xs font-medium text-gray-500 mb-1.5">{label}</label>}
      <div className="flex gap-1.5 flex-wrap">
        {TIER_ORDER.map((tier) => {
          const m = TIER_META[tier];
          const Icon = m.icon;
          const selected = value === tier;
          return (
            <button key={tier} onClick={() => onChange(tier)}
              className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                selected
                  ? 'bg-indigo-50 border-2 border-indigo-400 text-indigo-700 shadow-sm'
                  : 'bg-gray-50 border border-gray-200 text-gray-600 hover:bg-gray-100'
              }`}>
              <Icon size={13} className={selected ? m.color : 'text-gray-400'} />
              {m.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── LLM Provider Section ──────────────────────────────────────

function LLMProviderSection() {
  const queryClient = useQueryClient();
  const { data: providers, isLoading } = useQuery({
    queryKey: ['llm-providers'],
    queryFn: () => apiClient.getLLMProviders(),
  });

  const [edits, setEdits] = useState<Record<string, { model: string; api_key: string; base_url: string }>>({});
  const [showKeys, setShowKeys] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState('');

  // Init edits from loaded providers
  useEffect(() => {
    if (providers && Object.keys(edits).length === 0) {
      const init: typeof edits = {};
      for (const [tier, info] of Object.entries(providers as Record<string, LLMProviderInfo>)) {
        init[tier] = { model: info.model, api_key: '', base_url: info.base_url };
      }
      setEdits(init);
    }
  }, [providers]);

  if (isLoading || !providers) return <div className="text-gray-400 text-sm py-4">加载中...</div>;

  const handleSave = async (tier: string) => {
    const e = edits[tier];
    if (!e) return;
    setSaving(tier);
    setMsg('');
    try {
      const patch: Record<string, string> = {};
      const orig = (providers as Record<string, LLMProviderInfo>)[tier];
      if (e.model !== orig.model) patch.model = e.model;
      if (e.api_key) patch.api_key = e.api_key;
      if (e.base_url !== orig.base_url) patch.base_url = e.base_url;
      if (Object.keys(patch).length === 0) {
        setMsg('无修改');
        setSaving(null);
        return;
      }
      await apiClient.updateLLMProvider(tier, patch);
      queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
      // Clear the key field after save
      setEdits(prev => ({ ...prev, [tier]: { ...prev[tier], api_key: '' } }));
      setMsg(`${TIER_META[tier]?.label} 已保存`);
      setTimeout(() => setMsg(''), 2000);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(null);
    }
  };

  const handleResetAll = async () => {
    if (!confirm('确定恢复所有模型配置为 .env 默认值？')) return;
    await apiClient.resetLLMProviders();
    queryClient.invalidateQueries({ queryKey: ['llm-providers'] });
    setEdits({});
    setMsg('已恢复默认');
    setTimeout(() => setMsg(''), 2000);
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server size={18} className="text-indigo-600" />
          <h2 className="text-lg font-semibold text-gray-900">模型配置</h2>
        </div>
        <div className="flex items-center gap-2">
          {msg && <span className={`text-xs ${msg.includes('失败') ? 'text-red-500' : 'text-green-600'}`}>{msg}</span>}
          <button onClick={handleResetAll}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            <RotateCcw size={12} /> 全部重置
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {TIER_ORDER.map((tier) => {
          const info = (providers as Record<string, LLMProviderInfo>)[tier];
          const meta = TIER_META[tier];
          const Icon = meta.icon;
          const e = edits[tier] || { model: info?.model || '', api_key: '', base_url: info?.base_url || '' };
          const keyVisible = showKeys[tier];

          return (
            <div key={tier} className={`rounded-lg border border-gray-200 p-4 space-y-3 ${meta.bg} bg-opacity-30`}>
              {/* Tier header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Icon size={16} className={meta.color} />
                  <span className="font-semibold text-sm">{meta.label}</span>
                  <span className="text-[10px] text-gray-400 font-mono">{info?.provider}</span>
                </div>
                {info?.api_key_set ? (
                  <span className="text-[10px] px-1.5 py-0.5 bg-green-100 text-green-700 rounded">Key 已配置</span>
                ) : (
                  <span className="text-[10px] px-1.5 py-0.5 bg-red-100 text-red-600 rounded">未配置</span>
                )}
              </div>

              {/* Model name */}
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">模型名称</label>
                <input type="text" value={e.model}
                  onChange={(ev) => setEdits(prev => ({
                    ...prev, [tier]: { ...prev[tier], model: ev.target.value }
                  }))}
                  className="w-full px-2.5 py-1.5 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-indigo-400 font-mono"
                />
              </div>

              {/* API Key */}
              <div>
                <label className="flex items-center gap-1 text-[10px] text-gray-500 mb-1">
                  <Key size={10} /> API Key
                  {info?.api_key_masked && (
                    <span className="text-gray-400 font-mono">({info.api_key_masked})</span>
                  )}
                </label>
                <div className="flex gap-1.5">
                  <div className="relative flex-1">
                    <input
                      type={keyVisible ? 'text' : 'password'}
                      value={e.api_key}
                      onChange={(ev) => setEdits(prev => ({
                        ...prev, [tier]: { ...prev[tier], api_key: ev.target.value }
                      }))}
                      placeholder="输入新Key覆盖"
                      className="w-full px-2.5 py-1.5 pr-8 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-indigo-400 font-mono"
                    />
                    <button onClick={() => setShowKeys(prev => ({ ...prev, [tier]: !prev[tier] }))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      {keyVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
              </div>

              {/* Base URL (only for fast/deepseek) */}
              {(tier === 'fast' || e.base_url) && (
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">Base URL</label>
                  <input type="text" value={e.base_url}
                    onChange={(ev) => setEdits(prev => ({
                      ...prev, [tier]: { ...prev[tier], base_url: ev.target.value }
                    }))}
                    placeholder="https://api.deepseek.com/v1"
                    className="w-full px-2.5 py-1.5 text-sm border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-indigo-400 font-mono"
                  />
                </div>
              )}

              {/* Save button */}
              <button onClick={() => handleSave(tier)} disabled={saving === tier}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors">
                <Save size={12} />
                {saving === tier ? '保存中...' : '保存'}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Plugin Card ───────────────────────────────────────────────

function PluginCard({ config, onSaved }: { config: AgentConfig; onSaved: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<AgentConfigDetail | null>(null);
  const [editPrompt, setEditPrompt] = useState('');
  const [editTier, setEditTier] = useState(config.model_tier);
  const [editGenTier, setEditGenTier] = useState(config.gen_model_tier);
  const [editEnabled, setEditEnabled] = useState(config.enabled);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  const info = PLUGIN_LABELS[config.name] || { zh: config.name, desc: '' };

  const handleExpand = async () => {
    if (!expanded && !detail) {
      try {
        const d = await apiClient.getAgentConfig(config.name) as AgentConfigDetail;
        setDetail(d);
        setEditPrompt(d.system_prompt);
        setEditTier(d.model_tier);
        setEditGenTier(d.gen_model_tier || '');
        setEditEnabled(d.enabled);
      } catch {
        setMsg('加载失败');
      }
    }
    setExpanded(!expanded);
  };

  const handleSave = async () => {
    setSaving(true); setMsg('');
    try {
      const patch: Record<string, unknown> = {};
      if (editTier !== config.model_tier) patch.model_tier = editTier;
      if (editEnabled !== config.enabled) patch.enabled = editEnabled;
      if (config.gen_model_tier !== undefined && editGenTier !== config.gen_model_tier) {
        patch.gen_model_tier = editGenTier;
      }
      if (detail && editPrompt !== detail.system_prompt) patch.system_prompt = editPrompt;
      if (!Object.keys(patch).length) { setMsg('无修改'); setSaving(false); return; }
      await apiClient.updateAgentConfig(config.name, patch);
      setMsg('已保存'); onSaved();
      setTimeout(() => setMsg(''), 2000);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : '保存失败');
    } finally { setSaving(false); }
  };

  const handleReset = async () => {
    if (!confirm(`确定将 ${info.zh} 恢复默认？`)) return;
    setSaving(true);
    try {
      const d = await apiClient.resetAgentConfig(config.name) as AgentConfigDetail;
      setDetail(d); setEditPrompt(d.system_prompt);
      setEditTier(d.model_tier); setEditGenTier(d.gen_model_tier || '');
      setEditEnabled(d.enabled);
      setMsg('已恢复默认'); onSaved();
      setTimeout(() => setMsg(''), 2000);
    } catch { setMsg('重置失败'); }
    finally { setSaving(false); }
  };

  const tierMeta = TIER_META[config.model_tier];
  const TierIcon = tierMeta?.icon || Brain;

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden hover:shadow-sm transition-shadow">
      <button onClick={handleExpand}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50/50 transition-colors">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${config.enabled ? 'bg-indigo-50' : 'bg-gray-100'}`}>
          <Bot size={16} className={config.enabled ? 'text-indigo-600' : 'text-gray-400'} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-gray-900">{info.zh}</span>
            <span className="text-[10px] text-gray-400 font-mono">{config.name}</span>
            {config.has_custom_prompt && (
              <span className="px-1.5 py-0.5 bg-amber-50 text-amber-600 text-[10px] rounded font-medium">自定义</span>
            )}
            {!config.enabled && (
              <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 text-[10px] rounded font-medium">已禁用</span>
            )}
          </div>
          <p className="text-[11px] text-gray-500 mt-0.5">{info.desc}</p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <div className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${tierMeta?.color || 'text-gray-500'} bg-gray-50`}>
            <TierIcon size={12} />{tierMeta?.label || config.model_tier}
          </div>
          {expanded ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-4 space-y-4 bg-gray-50/30">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">启用</span>
            <button onClick={() => setEditEnabled(!editEnabled)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                editEnabled ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-gray-100 text-gray-500 border border-gray-200'
              }`}>
              {editEnabled ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
              {editEnabled ? '启用' : '禁用'}
            </button>
          </div>

          <TierSelect value={editTier} onChange={setEditTier} label="模型档位" />

          {config.default_gen_model_tier && (
            <TierSelect value={editGenTier || 'max'} onChange={setEditGenTier} label="页面生成模型（内部LLM调用）" />
          )}

          {detail && detail.default_system_prompt && (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1.5">
                系统提示词
                {config.has_custom_prompt && <span className="ml-2 text-amber-500">已修改</span>}
              </label>
              <textarea value={editPrompt} onChange={(e) => setEditPrompt(e.target.value)}
                rows={10}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-xs font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y bg-white"
                placeholder="留空则使用默认提示词" />
              <p className="text-[10px] text-gray-400 mt-1">
                提示词中的 {'{'}变量{'}'} 请勿删除（如 {'{event_id}'}, {'{today}'} 等）
              </p>
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <button onClick={handleSave} disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors">
              <Save size={14} />{saving ? '保存中...' : '保存'}
            </button>
            <button onClick={handleReset} disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-white text-gray-600 text-sm font-medium rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-50 transition-colors">
              <RotateCcw size={14} />恢复默认
            </button>
            {msg && <span className={`text-xs ml-2 ${msg.includes('失败') ? 'text-red-600' : 'text-green-600'}`}>{msg}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────

export function AgentSettingsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: configs, isLoading } = useQuery({
    queryKey: ['agent-configs'],
    queryFn: () => apiClient.getAgentConfigs(),
  });

  const handleSaved = () => {
    queryClient.invalidateQueries({ queryKey: ['agent-configs'] });
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto py-6 px-4 pb-20 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(-1)}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <ArrowLeft size={20} className="text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">AI Agent 设置</h1>
            <p className="text-sm text-gray-500 mt-0.5">配置模型、API Key、子Agent提示词和启用状态</p>
          </div>
        </div>

        {/* Section 1: LLM Providers */}
        <LLMProviderSection />

        {/* Section 2: Plugin configs */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Bot size={18} className="text-indigo-600" />
            <h2 className="text-lg font-semibold text-gray-900">Agent 插件配置</h2>
          </div>

          {isLoading ? (
            <div className="text-center py-8 text-gray-500">加载中...</div>
          ) : (
            <div className="space-y-2">
              {(configs as AgentConfig[] || []).map((c) => (
                <PluginCard key={c.name} config={c} onSaved={handleSaved} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
