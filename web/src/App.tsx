import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, ProtectedRoute } from './lib/auth';
import { Layout } from './components/Layout';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { EventListPage } from './pages/EventListPage';
import { EventDetailPage } from './pages/EventDetailPage';
import { BadgeTemplatesPage } from './pages/BadgeTemplatesPage';
import { AssistantPage } from './pages/AssistantPage';
import { AgentSettingsPage } from './pages/AgentSettingsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1000 * 60 * 5, gcTime: 1000 * 60 * 10 },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <Routes>
            {/* Auth Pages */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />

            {/* Protected Pages */}
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout>
                    <EventListPage />
                  </Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/events/:id"
              element={
                <ProtectedRoute>
                  <Layout>
                    <EventDetailPage />
                  </Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/assistant"
              element={
                <ProtectedRoute>
                  <Layout>
                    <AssistantPage />
                  </Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/agent-settings"
              element={
                <ProtectedRoute>
                  <Layout>
                    <AgentSettingsPage />
                  </Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/templates"
              element={
                <ProtectedRoute>
                  <Layout>
                    <BadgeTemplatesPage />
                  </Layout>
                </ProtectedRoute>
              }
            />

            {/* Redirect unknown routes to home */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;
