// Shared component-type palette used by both the systems and environment diagrams.
export const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2', // blue
  cache: '#f57c00', // amber
  message_queue: '#7b1fa2', // purple
  web_service: '#388e3c', // green
  api_gateway: '#00796b', // teal
  worker: '#e64a19', // orange
  frontend: '#303f9f', // indigo
  other: '#616161', // grey
};

/** Colour for a mocked subsystem, regardless of its component type. */
export const MOCK_COLOR = '#9e9e9e';

/** Faint background wash for a mocked subsystem node — the MOCK_COLOR tint (#9e9e9e = 158,158,158). */
export const MOCK_BG = 'rgba(158,158,158,0.06)';

export const colorForComponentType = (t: string): string =>
  COMPONENT_COLORS[t] ?? COMPONENT_COLORS.other;
