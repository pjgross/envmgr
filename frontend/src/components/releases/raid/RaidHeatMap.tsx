/**
 * RaidHeatMap — probability × impact grid coloured by the tenant's RAG bands.
 * Rows are probability (high at top), columns are impact (low → high).
 * When `heatmap` ref-codes are supplied, each cell lists the items scored there.
 */
import { Box, Tooltip, Typography } from '@mui/material';
import type { RaidConfig } from '../../../types/raid';
import { severityColor, contrastText } from './raidConstants';

interface Props {
  config: RaidConfig | null;
  // heatmap[probability-1][impact-1] = [ref_code, ...]
  heatmap?: string[][][];
  compact?: boolean;
}

export default function RaidHeatMap({ config, heatmap, compact }: Props) {
  if (!config) return null;
  const probs = [...config.probability_scale].sort((a, b) => a.level - b.level);
  const impacts = [...config.impact_scale].sort((a, b) => a.level - b.level);
  const cell = compact ? 40 : 64;

  return (
    <Box>
      <Box sx={{ display: 'flex' }}>
        {/* Y axis label */}
        <Box
          sx={{
            width: 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            writingMode: 'vertical-rl',
            transform: 'rotate(180deg)',
          }}
        >
          <Typography variant="caption" color="text.secondary">Probability</Typography>
        </Box>

        <Box>
          {/* Rows: highest probability first */}
          {[...probs].reverse().map((p) => (
            <Box key={p.level} sx={{ display: 'flex' }}>
              <Box
                sx={{
                  width: 90,
                  height: cell,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  pr: 1,
                }}
              >
                <Typography variant="caption" noWrap>{p.level}. {p.label}</Typography>
              </Box>
              {impacts.map((i) => {
                const severity = p.level * i.level;
                const refs = heatmap?.[p.level - 1]?.[i.level - 1] ?? [];
                return (
                  <Tooltip
                    key={i.level}
                    title={refs.length ? `${refs.join(', ')} (severity ${severity})` : `severity ${severity}`}
                  >
                    <Box
                      sx={{
                        width: cell,
                        height: cell,
                        bgcolor: severityColor(severity, config),
                        border: '1px solid rgba(255,255,255,0.6)',
                        color: contrastText(severityColor(severity, config)),
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        overflow: 'hidden',
                      }}
                    >
                      {compact ? (
                        <Typography variant="caption">{severity}</Typography>
                      ) : (
                        <>
                          <Typography variant="caption" sx={{ fontWeight: 600 }}>{severity}</Typography>
                          {refs.length > 0 && (
                            <Typography variant="caption" noWrap sx={{ fontSize: 10, maxWidth: cell - 6 }}>
                              {refs.length <= 2 ? refs.join(',') : `${refs.length} items`}
                            </Typography>
                          )}
                        </>
                      )}
                    </Box>
                  </Tooltip>
                );
              })}
            </Box>
          ))}
          {/* X axis tick labels */}
          <Box sx={{ display: 'flex', ml: '90px' }}>
            {impacts.map((i) => (
              <Box key={i.level} sx={{ width: cell, textAlign: 'center' }}>
                <Typography variant="caption" noWrap>{i.level}</Typography>
              </Box>
            ))}
          </Box>
          <Box sx={{ display: 'flex', ml: '90px', justifyContent: 'center' }}>
            <Typography variant="caption" color="text.secondary">Impact</Typography>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
