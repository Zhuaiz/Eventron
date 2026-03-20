/**
 * API client with typed endpoints
 * Automatically includes auth token in Bearer header
 */

const API_BASE = '/api';

interface ApiError {
  detail?: string;
  message?: string;
}

export class ApiClient {
  private getToken(): string | null {
    return localStorage.getItem('token');
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestInit
  ): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (options?.headers && typeof options.headers === 'object') {
      Object.assign(headers, options.headers);
    }

    const token = this.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      ...options,
    });

    if (response.status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }

    if (!response.ok) {
      const errorData = (await response.json()) as ApiError;
      throw new Error(errorData.detail || errorData.message || 'API Error');
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json() as Promise<T>;
  }

  // Auth
  async login(email: string, password: string) {
    return this.request('POST', '/v1/auth/login', { email, password });
  }

  async register(email: string, password: string, name: string, phone?: string) {
    return this.request('POST', '/v1/auth/register', { email, password, name, phone });
  }

  async getMe() {
    return this.request('GET', '/v1/auth/me');
  }

  // Events
  async getEvents(status?: string) {
    const query = status ? `?status=${status}` : '';
    return this.request('GET', `/events/${query}`);
  }

  async getEvent(eventId: string) {
    return this.request('GET', `/events/${eventId}`);
  }

  async createEvent(data: {
    name: string;
    event_date?: string;
    location?: string;
    venue_rows: number;
    venue_cols: number;
    layout_type: string;
    config?: Record<string, unknown>;
  }) {
    return this.request('POST', '/events/', data);
  }

  async updateEvent(eventId: string, data: Record<string, unknown>) {
    return this.request('PATCH', `/events/${eventId}`, data);
  }

  async deleteEvent(eventId: string) {
    return this.request('DELETE', `/events/${eventId}`);
  }

  async activateEvent(eventId: string) {
    return this.request('POST', `/events/${eventId}/activate`, {});
  }

  async duplicateEvent(eventId: string) {
    return this.request('POST', `/events/${eventId}/duplicate`, {});
  }

  // Attendees
  async getAttendees(eventId: string, params?: Record<string, string>) {
    const query = new URLSearchParams(params || {}).toString();
    const separator = query ? '?' : '';
    return this.request('GET', `/events/${eventId}/attendees${separator}${query}`);
  }

  async createAttendee(
    eventId: string,
    data: {
      name: string;
      title?: string;
      organization?: string;
      role: string;
      phone?: string;
      email?: string;
    }
  ) {
    return this.request('POST', `/events/${eventId}/attendees`, data);
  }

  async updateAttendee(eventId: string, attendeeId: string, data: Record<string, unknown>) {
    return this.request('PATCH', `/events/${eventId}/attendees/${attendeeId}`, data);
  }

  async deleteAttendee(eventId: string, attendeeId: string) {
    return this.request('DELETE', `/events/${eventId}/attendees/${attendeeId}`);
  }

  async checkinAttendee(eventId: string, attendeeId: string) {
    return this.request('POST', `/events/${eventId}/attendees/${attendeeId}/checkin`, {});
  }

  // Dashboard
  async getDashboard(eventId: string) {
    return this.request('GET', `/v1/dashboard/${eventId}`);
  }

  // Import
  async previewImport(eventId: string, file: File) {
    const formData = new FormData();
    formData.append('file', file);

    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE}/v1/events/${eventId}/attendees/import-preview`,
      { method: 'POST', headers, body: formData }
    );

    if (response.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      const errorData = (await response.json()) as ApiError;
      throw new Error(errorData.detail || 'Import preview failed');
    }
    return response.json();
  }

  async confirmImport(
    eventId: string,
    data: { column_mapping: Record<string, string>; attendees_data: unknown[] }
  ) {
    return this.request('POST', `/v1/events/${eventId}/attendees/import-confirm`, data);
  }

  // Seats
  async getSeats(eventId: string) {
    return this.request('GET', `/events/${eventId}/seats`);
  }

  async createSeatGrid(eventId: string, rows: number, cols: number) {
    return this.request('POST', `/events/${eventId}/seats/grid?rows=${rows}&cols=${cols}`, {});
  }

  async autoAssignSeats(eventId: string, strategy: string = 'random') {
    return this.request('POST', `/events/${eventId}/seats/auto-assign`, { strategy });
  }

  async updateSeat(eventId: string, seatId: string, data: Record<string, unknown>) {
    return this.request('PATCH', `/events/${eventId}/seats/${seatId}`, data);
  }

  async suggestZones(eventId: string) {
    return this.request<{ zones: any[]; total_rows: number }>(
      'GET', `/events/${eventId}/seats/suggest-zones`
    );
  }

  async assignSeat(eventId: string, seatId: string, attendeeId: string) {
    return this.request('POST', `/events/${eventId}/seats/${seatId}/assign?attendee_id=${attendeeId}`, {});
  }

  async swapSeats(eventId: string, seatAId: string, seatBId: string) {
    return this.request('POST', `/events/${eventId}/seats/swap?seat_a_id=${seatAId}&seat_b_id=${seatBId}`, {});
  }

  // Export
  getExportAttendeesUrl(eventId: string) {
    return `${API_BASE}/v1/events/${eventId}/export/attendees`;
  }

  getExportSeatmapUrl(eventId: string) {
    return `${API_BASE}/v1/events/${eventId}/export/seatmap`;
  }

  getExportBadgesUrl(eventId: string, templateName = 'business', templateId?: string) {
    const params = new URLSearchParams({ template_name: templateName });
    if (templateId) params.set('template_id', templateId);
    return `${API_BASE}/v1/events/${eventId}/export/badges?${params}`;
  }

  // ── Event Files ──────────────────────────────────────────────
  async uploadEventFile(eventId: string, file: File) {
    const formData = new FormData();
    formData.append('file', file);

    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(
      `${API_BASE}/v1/events/${eventId}/files`,
      { method: 'POST', headers, body: formData }
    );
    if (response.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      const err = (await response.json()) as ApiError;
      throw new Error(err.detail || 'Upload failed');
    }
    return response.json();
  }

  async listEventFiles(eventId: string) {
    return this.request('GET', `/v1/events/${eventId}/files`);
  }

  getEventFileUrl(eventId: string, fileId: string) {
    return `${API_BASE}/v1/events/${eventId}/files/${fileId}`;
  }

  async deleteEventFile(eventId: string, fileId: string) {
    return this.request('DELETE', `/v1/events/${eventId}/files/${fileId}`);
  }

  // ── Agent Chat (multipart for files) ─────────────────────────
  async sendAgentChat(
    message: string,
    opts?: {
      eventId?: string;
      sessionId?: string;
      scope?: string;   // e.g. "organizer", "badge", "checkin"
      files?: File[];
    }
  ): Promise<{
    reply: string;
    session_id: string;
    event_id: string | null;
    action_taken: string | null;
    task_plan: any[] | null;
  }> {
    const formData = new FormData();
    formData.append('message', message);
    if (opts?.eventId) formData.append('event_id', opts.eventId);
    if (opts?.sessionId) formData.append('session_id', opts.sessionId);
    if (opts?.scope) formData.append('scope', opts.scope);
    if (opts?.files) opts.files.forEach((f) => formData.append('files', f));

    const token = this.getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${API_BASE}/v1/agent/chat`, {
      method: 'POST', headers, body: formData,
    });
    if (response.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      const err = (await response.json()) as ApiError;
      throw new Error(err.detail || 'Chat error');
    }
    return response.json();
  }

  // Legacy text-only chat (backward compat)
  async sendChatMessage(message: string, eventId?: string, sessionId?: string) {
    return this.sendAgentChat(message, { eventId, sessionId });
  }

  // Badge Templates
  async getBadgeTemplates(templateType?: string) {
    const query = templateType ? `?template_type=${templateType}` : '';
    return this.request('GET', `/v1/badge-templates/${query}`);
  }

  async createBadgeTemplate(data: {
    name: string;
    template_type: string;
    html_template: string;
    css: string;
    style_category?: string;
  }) {
    return this.request('POST', '/v1/badge-templates/', data);
  }

  async updateBadgeTemplate(templateId: string, data: Record<string, unknown>) {
    return this.request('PATCH', `/v1/badge-templates/${templateId}`, data);
  }

  async deleteBadgeTemplate(templateId: string) {
    return this.request('DELETE', `/v1/badge-templates/${templateId}`);
  }
}

export const apiClient = new ApiClient();
