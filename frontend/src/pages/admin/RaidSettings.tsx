/**
 * RaidSettings — tenant admin page to edit RAID probability/impact scales
 * and RAG bands, with a live heat-map preview.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchRaidConfig, updateRaidConfig } from '../../store/raidSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { RaidScaleLevel, RaidBand, RaidConfig } from '../../types/raid';
import RaidHeatMap from '../../components/releases/raid/RaidHeatMap';
import { titleCase } from '../../components/releases/raid/raidConstants';
import PageHeader from '../../components/layout/PageHeader';

function ScaleEditor({
  title,
  scale,
  onChange,
}: {
  title: string;
  scale: RaidScaleLevel[];
  onChange: (next: RaidScaleLevel[]) => void;
}) {
  const setAt = (idx: number, patch: Partial<RaidScaleLevel>) =>
    onChange(scale.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>{title}</Typography>
      <Stack spacing={1}>
        {scale.map((lvl, idx) => (
          <Stack key={lvl.level} direction="row" spacing={1} alignItems="center">
            <Typography sx={{ width: 24 }}>{lvl.level}</Typography>
            <TextField
              size="small"
              label="Label"
              value={lvl.label}
              onChange={(e) => setAt(idx, { label: e.target.value })}
              sx={{ flexGrow: 1 }}
            />
            <input
              type="color"
              value={lvl.color}
              onChange={(e) => setAt(idx, { color: e.target.value })}
              aria-label={`${title} level ${lvl.level} colour`}
            />
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}

function BandEditor({
  bands,
  onChange,
}: {
  bands: RaidBand[];
  onChange: (next: RaidBand[]) => void;
}) {
  const setAt = (idx: number, patch: Partial<RaidBand>) =>
    onChange(bands.map((b, i) => (i === idx ? { ...b, ...patch } : b)));

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" gutterBottom>RAG bands (severity ranges)</Typography>
      <Stack spacing={1}>
        {bands.map((band, idx) => (
          <Stack key={band.rag} direction="row" spacing={1} alignItems="center">
            <Typography sx={{ width: 64 }}>{titleCase(band.rag)}</Typography>
            <TextField
              size="small"
              label="Min"
              type="number"
              value={band.min}
              onChange={(e) => setAt(idx, { min: Number(e.target.value) })}
              sx={{ width: 90 }}
            />
            <TextField
              size="small"
              label="Max"
              type="number"
              value={band.max}
              onChange={(e) => setAt(idx, { max: Number(e.target.value) })}
              sx={{ width: 90 }}
            />
            <input
              type="color"
              value={band.color}
              onChange={(e) => setAt(idx, { color: e.target.value })}
              aria-label={`${band.rag} band colour`}
            />
          </Stack>
        ))}
      </Stack>
    </Paper>
  );
}

export default function RaidSettings() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const config = useSelector((s: RootState) => s.raid.config);

  const [probability, setProbability] = useState<RaidScaleLevel[]>([]);
  const [impact, setImpact] = useState<RaidScaleLevel[]>([]);
  const [bands, setBands] = useState<RaidBand[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    dispatch(fetchRaidConfig());
  }, [dispatch]);

  useEffect(() => {
    if (config) {
      setProbability(config.probability_scale);
      setImpact(config.impact_scale);
      setBands(config.rag_bands);
    }
  }, [config]);

  const previewConfig: RaidConfig = {
    probability_scale: probability,
    impact_scale: impact,
    rag_bands: bands,
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await dispatch(
        updateRaidConfig({
          probability_scale: probability,
          impact_scale: impact,
          rag_bands: bands,
        }),
      ).unwrap();
      snackbar.success('RAID settings saved');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save RAID settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="RAID settings"
        subtitle="Configure the probability and impact scales and the RAG bands used to score risks and issues. Severity = probability × impact."
      />

      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={3}>
        <Stack spacing={2} sx={{ flex: 1 }}>
          <ScaleEditor title="Probability scale" scale={probability} onChange={setProbability} />
          <ScaleEditor title="Impact scale" scale={impact} onChange={setImpact} />
          <BandEditor bands={bands} onChange={setBands} />
          <Box>
            <Button variant="contained" onClick={handleSave} disabled={saving || !config}>
              Save changes
            </Button>
          </Box>
        </Stack>

        <Paper variant="outlined" sx={{ p: 2, alignSelf: 'flex-start' }}>
          <Typography variant="subtitle2" gutterBottom>Live preview</Typography>
          <RaidHeatMap config={previewConfig} />
        </Paper>
      </Stack>
    </Box>
  );
}
