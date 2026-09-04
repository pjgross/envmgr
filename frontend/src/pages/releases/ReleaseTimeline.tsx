/**
 * ReleaseTimeline — multi-release Gantt read-only view.
 * Backed by GET /api/v1/releases/timeline
 *
 * Rows = releases, bars = phases.
 * Implemented as a CSS/SVG Gantt rather than a drag-drop library (per plan latitude).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Chip,
  CircularProgress,
  Divider,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchReleaseTimeline } from '../../store/releaseSlice';
import DependencyAlertBanner from '../../components/releases/DependencyAlertBanner';
import type { ReleaseTimelineEntry } from '../../types/release';
import PageHeader from '../../components/layout/PageHeader';

const PHASE_STATUS_COLORS: Record<string, string> = {
  pending: '#9e9e9e',
  in_progress: '#1976d2',
  completed: '#388e3c',
  skipped: '#bdbdbd',
};

const GATE_STATUS_COLORS: Record<string, string> = {
  pending: '#607d8b',     // slate — not yet decided
  passed: '#43a047',      // green
  failed: '#e53935',      // red — draws the eye
  overridden: '#ffb300',  // amber — distinct from orange target_date
};

const RELEASE_STATUS_CHIP: Record<string, { color: 'default' | 'primary' | 'success' | 'warning' | 'error'; label: string }> = {
  draft: { color: 'default', label: 'Draft' },
  planning: { color: 'default', label: 'Planning' },
  in_progress: { color: 'primary', label: 'In Progress' },
  completed: { color: 'success', label: 'Completed' },
  cancelled: { color: 'error', label: 'Cancelled' },
};

const ROW_HEIGHT = 48;
const LABEL_WIDTH = 220;
const MIN_BAR_WIDTH = 8;
const HEADER_HEIGHT = 40;

function computeDateRange(entries: ReleaseTimelineEntry[]): { minDate: Date; maxDate: Date } {
  const dates: Date[] = [];
  for (const e of entries) {
    if (e.target_date) dates.push(new Date(e.target_date));
    if (e.actual_date) dates.push(new Date(e.actual_date));
    for (const p of e.phases) {
      if (p.start_date) dates.push(new Date(p.start_date));
      if (p.end_date) dates.push(new Date(p.end_date));
    }
    for (const g of e.gates ?? []) {
      dates.push(new Date(g.due_date));
    }
  }
  if (dates.length === 0) {
    const now = new Date();
    return {
      minDate: new Date(now.getFullYear(), now.getMonth(), 1),
      maxDate: new Date(now.getFullYear(), now.getMonth() + 3, 0),
    };
  }
  const min = new Date(Math.min(...dates.map((d) => d.getTime())));
  const max = new Date(Math.max(...dates.map((d) => d.getTime())));
  // Pad a bit
  min.setDate(min.getDate() - 7);
  max.setDate(max.getDate() + 7);
  return { minDate: min, maxDate: max };
}

function dateToX(date: Date, minDate: Date, totalDays: number, chartWidth: number): number {
  const days = (date.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24);
  return (days / totalDays) * chartWidth;
}

interface GanttBarProps {
  phase: ReleaseTimelineEntry['phases'][number];
  rowIndex: number;
  minDate: Date;
  totalDays: number;
  chartWidth: number;
}

function GanttBar({ phase, rowIndex, minDate, totalDays, chartWidth }: GanttBarProps) {
  if (!phase.start_date) return null;
  const start = new Date(phase.start_date);
  const end = phase.end_date ? new Date(phase.end_date) : start;
  const x = dateToX(start, minDate, totalDays, chartWidth);
  const endX = dateToX(end, minDate, totalDays, chartWidth);
  const width = Math.max(endX - x, MIN_BAR_WIDTH);
  const color = PHASE_STATUS_COLORS[phase.status] ?? '#1976d2';
  const y = rowIndex * ROW_HEIGHT + (ROW_HEIGHT - 20) / 2 + HEADER_HEIGHT;

  return (
    <Tooltip title={`${phase.name} (${phase.status})`} placement="top">
      <rect
        x={x}
        y={y}
        width={width}
        height={20}
        rx={3}
        fill={color}
        opacity={0.85}
        style={{ cursor: 'pointer' }}
      />
    </Tooltip>
  );
}

interface Props {
  releaseId?: number;
  alerts?: RootState['release']['dependencyAlerts'];
}

export default function ReleaseTimeline({ releaseId, alerts = [] }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { timeline, loading } = useSelector((state: RootState) => state.release);
  const containerRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(800);

  useEffect(() => {
    dispatch(fetchReleaseTimeline({}));
  }, [dispatch]);

  useEffect(() => {
    if (!containerRef.current) return;
    const obs = new ResizeObserver((entries) => {
      const w = entries[0].contentRect.width;
      setChartWidth(Math.max(w - LABEL_WIDTH - 24, 400));
    });
    obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  const { minDate, maxDate } = useMemo(() => computeDateRange(timeline), [timeline]);
  const totalDays = Math.max(
    (maxDate.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24),
    30
  );

  const svgHeight = timeline.length * ROW_HEIGHT + HEADER_HEIGHT;

  // Generate month tick marks
  const ticks = useMemo(() => {
    const result: { x: number; label: string }[] = [];
    const cur = new Date(minDate.getFullYear(), minDate.getMonth(), 1);
    while (cur <= maxDate) {
      const x = dateToX(cur, minDate, totalDays, chartWidth);
      result.push({
        x,
        label: cur.toLocaleString('default', { month: 'short', year: '2-digit' }),
      });
      cur.setMonth(cur.getMonth() + 1);
    }
    return result;
  }, [minDate, maxDate, totalDays, chartWidth]);

  // Today line
  const todayX = useMemo(
    () => dateToX(new Date(), minDate, totalDays, chartWidth),
    [minDate, totalDays, chartWidth]
  );

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Release timeline"
        subtitle="Gantt view of all release phases. Click a release name to open it."
      />

      {releaseId && alerts.length > 0 && (
        <DependencyAlertBanner releaseId={releaseId} alerts={alerts} />
      )}

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {!loading && timeline.length === 0 && (
        <Typography color="text.secondary">No releases with phases found.</Typography>
      )}

      {timeline.length > 0 && (
        <Paper variant="outlined" ref={containerRef} sx={{ overflow: 'auto' }}>
          <Box sx={{ display: 'flex' }}>
            {/* Label column */}
            <Box sx={{ width: LABEL_WIDTH, flexShrink: 0, borderRight: 1, borderColor: 'divider' }}>
              {/* Header spacer */}
              <Box sx={{ height: HEADER_HEIGHT, borderBottom: 1, borderColor: 'divider' }} />
              {timeline.map((entry, i) => {
                const chip = RELEASE_STATUS_CHIP[entry.status] ?? { color: 'default', label: entry.status };
                return (
                  <Box
                    key={entry.id}
                    sx={{
                      height: ROW_HEIGHT,
                      display: 'flex',
                      alignItems: 'center',
                      px: 1.5,
                      gap: 1,
                      borderBottom: i < timeline.length - 1 ? 1 : 0,
                      borderColor: 'divider',
                      cursor: 'pointer',
                      '&:hover': { bgcolor: 'action.hover' },
                    }}
                    onClick={() => navigate(`/releases/${entry.id}`)}
                  >
                    <Box sx={{ flexGrow: 1, overflow: 'hidden' }}>
                      <Typography variant="body2" noWrap>
                        {entry.name}
                      </Typography>
                    </Box>
                    <Chip
                      label={chip.label}
                      color={chip.color}
                      size="small"
                      sx={{ height: 18, fontSize: 10 }}
                    />
                  </Box>
                );
              })}
            </Box>

            {/* Gantt SVG column */}
            <Box sx={{ flexGrow: 1, overflow: 'auto' }}>
              <svg width={chartWidth} height={svgHeight} style={{ display: 'block' }}>
                {/* Month ticks header */}
                {ticks.map((tick) => (
                  <g key={tick.label}>
                    <line
                      x1={tick.x}
                      y1={0}
                      x2={tick.x}
                      y2={svgHeight}
                      stroke="#e0e0e0"
                      strokeWidth={1}
                    />
                    <text x={tick.x + 4} y={HEADER_HEIGHT - 10} fontSize={11} fill="#888">
                      {tick.label}
                    </text>
                  </g>
                ))}

                {/* Today line */}
                {todayX >= 0 && todayX <= chartWidth && (
                  <line
                    x1={todayX}
                    y1={HEADER_HEIGHT}
                    x2={todayX}
                    y2={svgHeight}
                    stroke="#ef5350"
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                  />
                )}

                {/* Row stripes + bars */}
                {timeline.map((entry, rowIndex) => (
                  <g key={entry.id}>
                    {/* Row stripe */}
                    <rect
                      x={0}
                      y={rowIndex * ROW_HEIGHT + HEADER_HEIGHT}
                      width={chartWidth}
                      height={ROW_HEIGHT}
                      fill={rowIndex % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)'}
                    />
                    {/* Phase bars */}
                    {entry.phases.map((phase) => (
                      <GanttBar
                        key={phase.id}
                        phase={phase}
                        rowIndex={rowIndex}
                        minDate={minDate}
                        totalDays={totalDays}
                        chartWidth={chartWidth}
                      />
                    ))}
                    {/* Target date diamond */}
                    {entry.target_date && (() => {
                      const tx = dateToX(new Date(entry.target_date), minDate, totalDays, chartWidth);
                      const cy = rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2 + HEADER_HEIGHT;
                      const s = 7;
                      return (
                        <Tooltip title={`Target: ${entry.target_date}`} placement="top">
                          <polygon
                            points={`${tx},${cy - s} ${tx + s},${cy} ${tx},${cy + s} ${tx - s},${cy}`}
                            fill="#ff9800"
                            opacity={0.9}
                          />
                        </Tooltip>
                      );
                    })()}
                    {/* Gate diamonds */}
                    {(entry.gates ?? []).map((gate) => {
                      const gx = dateToX(new Date(gate.due_date), minDate, totalDays, chartWidth);
                      const cy = rowIndex * ROW_HEIGHT + ROW_HEIGHT / 2 + HEADER_HEIGHT;
                      const s = 7;
                      const fill = GATE_STATUS_COLORS[gate.status] ?? '#607d8b';
                      return (
                        <Tooltip
                          key={`gate-${gate.id}`}
                          title={`${gate.name} — ${gate.status} — due ${gate.due_date.slice(0, 10)}`}
                          placement="top"
                        >
                          <polygon
                            points={`${gx},${cy - s} ${gx + s},${cy} ${gx},${cy + s} ${gx - s},${cy}`}
                            fill={fill}
                            opacity={0.95}
                            stroke="#fff"
                            strokeWidth={1}
                          />
                        </Tooltip>
                      );
                    })}
                  </g>
                ))}

                {/* Dependency arrows (SVG lines between releases) */}
                {timeline.map((entry) =>
                  (entry.dependencies ?? [])
                    .filter((dep) =>
                      timeline.some((t) => t.id === dep.depends_on_release_id)
                    )
                    .map((dep) => {
                      const fromIdx = timeline.findIndex((t) => t.id === dep.depends_on_release_id);
                      const toIdx = timeline.findIndex((t) => t.id === entry.id);
                      if (fromIdx === -1 || toIdx === -1) return null;
                      const fromEntry = timeline[fromIdx];
                      const toEntry = entry;
                      // Anchor from target_date of upstream or last phase end
                      const fromDate = fromEntry.target_date
                        ? new Date(fromEntry.target_date)
                        : fromEntry.phases.length > 0 && fromEntry.phases[fromEntry.phases.length - 1].end_date
                        ? new Date(fromEntry.phases[fromEntry.phases.length - 1].end_date!)
                        : null;
                      const toDate = toEntry.phases.length > 0 && toEntry.phases[0].start_date
                        ? new Date(toEntry.phases[0].start_date)
                        : toEntry.target_date
                        ? new Date(toEntry.target_date)
                        : null;
                      if (!fromDate || !toDate) return null;
                      const x1 = dateToX(fromDate, minDate, totalDays, chartWidth);
                      const y1 = fromIdx * ROW_HEIGHT + ROW_HEIGHT / 2 + HEADER_HEIGHT;
                      const x2 = dateToX(toDate, minDate, totalDays, chartWidth);
                      const y2 = toIdx * ROW_HEIGHT + ROW_HEIGHT / 2 + HEADER_HEIGHT;
                      return (
                        <g key={`dep-${dep.id}`}>
                          <defs>
                            <marker
                              id={`arrow-${dep.id}`}
                              markerWidth="6"
                              markerHeight="6"
                              refX="3"
                              refY="3"
                              orient="auto"
                            >
                              <path d="M0,0 L0,6 L6,3 z" fill="#ff9800" />
                            </marker>
                          </defs>
                          <path
                            d={`M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`}
                            fill="none"
                            stroke="#ff9800"
                            strokeWidth={1.5}
                            strokeDasharray="4 3"
                            opacity={0.7}
                            markerEnd={`url(#arrow-${dep.id})`}
                          />
                        </g>
                      );
                    })
                )}
              </svg>
            </Box>
          </Box>

          {/* Legend */}
          <Divider />
          <Box sx={{ px: 2, py: 1, display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            {Object.entries(PHASE_STATUS_COLORS).map(([status, color]) => (
              <Box key={status} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box sx={{ width: 12, height: 12, borderRadius: 0.5, bgcolor: color }} />
                <Typography variant="caption">{status}</Typography>
              </Box>
            ))}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Box
                sx={{ width: 0, height: 0, borderLeft: '6px solid transparent', borderRight: '6px solid transparent', borderBottom: '12px solid #ff9800' }}
              />
              <Typography variant="caption">target date</Typography>
            </Box>
            {(['pending', 'passed', 'failed', 'overridden'] as const).map((s) => (
              <Box key={`gate-${s}`} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <Box
                  sx={{
                    width: 0,
                    height: 0,
                    borderLeft: '6px solid transparent',
                    borderRight: '6px solid transparent',
                    borderBottom: `12px solid ${GATE_STATUS_COLORS[s]}`,
                  }}
                />
                <Typography variant="caption">gate {s}</Typography>
              </Box>
            ))}
          </Box>
        </Paper>
      )}
    </Box>
  );
}
