import { Box, Chip, Divider, IconButton, Paper, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import type { ComponentDependencyResponse } from '../../types/dependency'

interface DependencyDetailPaneProps {
  dep: ComponentDependencyResponse
  onClose: () => void
}

export default function DependencyDetailPane({ dep, onClose }: DependencyDetailPaneProps) {
  return (
    <Paper
      elevation={0}
      sx={{
        width: 300,
        flexShrink: 0,
        borderLeft: 1,
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        overflowY: 'auto',
        borderRadius: 0,
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: 2,
          py: 1,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Typography variant="subtitle2">Link Details</Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Dependency metadata */}
      <Box sx={{ px: 2, py: 1.5, display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Box>
          <Typography variant="caption" color="text.secondary">From</Typography>
          <Typography variant="body2" fontWeight="medium">
            {dep.from_subsystem?.name ?? `SubSystem #${dep.from_subsystem_id}`}
          </Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">To</Typography>
          <Typography variant="body2" fontWeight="medium">{dep.to_subsystem.name}</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
          <Chip label={dep.dependency_type.replace(/_/g, ' ')} size="small" variant="outlined" />
          <Chip
            label={dep.direction === 'two_way' ? 'Two-way' : 'One-way'}
            size="small"
            variant="outlined"
            color={dep.direction === 'two_way' ? 'secondary' : 'default'}
          />
        </Box>
        {dep.protocol && (
          <Box>
            <Typography variant="caption" color="text.secondary">Protocol</Typography>
            <Typography variant="body2">
              {dep.protocol}{dep.port ? `:${dep.port}` : ''}
            </Typography>
          </Box>
        )}
        {dep.label && (
          <Box>
            <Typography variant="caption" color="text.secondary">Label</Typography>
            <Typography variant="body2">{dep.label}</Typography>
          </Box>
        )}
      </Box>

      <Divider />

      {/* Endpoints */}
      <Box sx={{ px: 2, py: 1.5 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Endpoints{dep.endpoints.length > 0 ? ` (${dep.endpoints.length})` : ''}
        </Typography>
        {dep.endpoints.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No endpoints documented.
          </Typography>
        ) : (
          dep.endpoints.map((ep) => (
            <Box
              key={ep.id}
              sx={{
                display: 'flex',
                gap: 1,
                alignItems: 'flex-start',
                py: 0.75,
                borderBottom: '1px solid',
                borderColor: 'divider',
                '&:last-child': { borderBottom: 'none' },
              }}
            >
              {ep.http_method && (
                <Chip
                  label={ep.http_method.toUpperCase()}
                  size="small"
                  sx={{
                    fontFamily: 'monospace',
                    fontWeight: 700,
                    fontSize: '0.65rem',
                    minWidth: 56,
                    flexShrink: 0,
                  }}
                />
              )}
              <Box sx={{ minWidth: 0 }}>
                <Typography
                  variant="body2"
                  sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}
                >
                  {ep.path}
                </Typography>
                {ep.description && (
                  <Typography variant="caption" color="text.secondary">
                    {ep.description}
                  </Typography>
                )}
              </Box>
            </Box>
          ))
        )}
      </Box>
    </Paper>
  )
}
