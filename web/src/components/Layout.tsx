import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Menu, X, LogOut } from 'lucide-react';
import { useAuth } from '../lib/auth';

export function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();

  const navItems = [
    { label: 'AI 助手', href: '/assistant', icon: '✨' },
    { label: '活动管理', href: '/', icon: '📅' },
    { label: '模板管理', href: '/templates', icon: '🎨' },
    { label: 'AI 设置', href: '/agent-settings', icon: '🤖' },
  ];

  const isActive = (href: string) => location.pathname === href;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <div
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-white shadow-lg transition-transform duration-200 ease-in-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } lg:relative lg:translate-x-0 lg:shadow-none`}
      >
        <div className="h-full flex flex-col">
          {/* Logo */}
          <div className="p-6 border-b border-gray-200">
            <h1 className="text-xl font-bold text-indigo-600">Eventron</h1>
            <p className="text-xs text-gray-500 mt-1">会场智能排座</p>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-6 space-y-2">
            {navItems.map((item) => (
              <button
                key={item.href}
                onClick={() => {
                  navigate(item.href);
                  setSidebarOpen(false);
                }}
                className={`w-full text-left px-4 py-3 rounded-lg transition-colors ${
                  isActive(item.href)
                    ? 'bg-indigo-100 text-indigo-700 font-medium'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
              >
                <span className="mr-2">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>

          {/* User Info */}
          <div className="p-6 border-t border-gray-200 space-y-3">
            {user && (
              <div className="pb-3 border-b border-gray-200">
                <p className="text-sm font-medium text-gray-900">{user.name}</p>
                <p className="text-xs text-gray-500">{user.email}</p>
              </div>
            )}
            <button
              onClick={handleLogout}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              <LogOut size={16} />
              退出登录
            </button>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <div className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between lg:hidden">
          <h1 className="text-lg font-bold text-indigo-600">Eventron</h1>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 hover:bg-gray-100 rounded-lg"
          >
            {sidebarOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>

        {/* Page Content */}
        <main className="flex-1 overflow-hidden flex flex-col">
          <div className="flex-1 p-4 lg:p-8 flex flex-col min-h-0 overflow-hidden">{children}</div>
        </main>
      </div>

      {/* Overlay for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

    </div>
  );
}
