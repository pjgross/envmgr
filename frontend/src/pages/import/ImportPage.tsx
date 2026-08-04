import { useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import UploadIcon from '@mui/icons-material/Upload';
import DownloadIcon from '@mui/icons-material/Download';

import type { AppDispatch, RootState } from '../../store';
import { importEnvironments, importSystems, clearImportResult } from '../../store/versionSlice';
import type { ImportResult } from '../../types/version';

// ---------------------------------------------------------------------------
// Per-section import widget
// ---------------------------------------------------------------------------

interface ImportSectionProps {
  title: string;
  onUpload: (file: File) => void;
  loading: boolean;
  result: ImportResult | null;
  error: string | null;
}

function ImportSection({ title, onUpload, loading, result, error }: ImportSectionProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
  };

  const handleUpload = () => {
    if (selectedFile) {
      onUpload(selectedFile);
    }
  };

  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        {title}
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap', mb: 2 }}>
        <Button variant="outlined" component="label" startIcon={<UploadIcon />} disabled={loading}>
          Choose File
          <input ref={fileInputRef} type="file" accept=".xlsx" hidden onChange={handleFileChange} />
        </Button>

        {selectedFile && (
          <Typography variant="body2" color="text.secondary">
            {selectedFile.name}
          </Typography>
        )}

        <Button
          variant="contained"
          onClick={handleUpload}
          disabled={!selectedFile || loading}
          startIcon={loading ? <CircularProgress size={16} /> : <UploadIcon />}
        >
          {loading ? 'Uploading…' : 'Upload'}
        </Button>

        <Tooltip title="Templates coming soon">
          <span>
            <Button variant="outlined" startIcon={<DownloadIcon />} disabled>
              Download Template
            </Button>
          </span>
        </Tooltip>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {result && (
        <>
          <Alert
            severity={
              result.errors.length > 0
                ? 'warning'
                : result.tier_fallbacks.length > 0
                  ? 'info'
                  : 'success'
            }
            sx={{ mb: 2 }}
          >
            Created {result.created}, Skipped {result.skipped}
            {result.errors.length > 0 && `, ${result.errors.length} error(s)`}
            {result.tier_fallbacks.length > 0 &&
              `, ${result.tier_fallbacks.length} assumption(s) made`}
          </Alert>

          {result.errors.length > 0 && (
            <TableContainer sx={{ mb: result.tier_fallbacks.length > 0 ? 2 : 0 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Row</TableCell>
                    <TableCell>Field</TableCell>
                    <TableCell>Message</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.errors.map((err, idx) => (
                    <TableRow key={idx}>
                      <TableCell>{err.row}</TableCell>
                      <TableCell>{err.field}</TableCell>
                      <TableCell>{err.message}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}

          {result.tier_fallbacks.length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Assumptions made
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Row</TableCell>
                      <TableCell>Field</TableCell>
                      <TableCell>Message</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {result.tier_fallbacks.map((fb, idx) => (
                      <TableRow key={idx}>
                        <TableCell>{fb.row}</TableCell>
                        <TableCell>{fb.field}</TableCell>
                        <TableCell>{fb.message}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}
        </>
      )}
    </Paper>
  );
}

// ---------------------------------------------------------------------------
// ImportPage
// ---------------------------------------------------------------------------

export default function ImportPage() {
  const dispatch = useDispatch<AppDispatch>();
  const { importLoading, importError, lastImportResult } = useSelector(
    (state: RootState) => state.version
  );

  // Track which section last triggered an import
  const [activeSection, setActiveSection] = useState<'environments' | 'systems' | null>(null);

  const handleImportEnvironments = (file: File) => {
    setActiveSection('environments');
    dispatch(clearImportResult());
    dispatch(importEnvironments(file));
  };

  const handleImportSystems = (file: File) => {
    setActiveSection('systems');
    dispatch(clearImportResult());
    dispatch(importSystems(file));
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" fontWeight="bold" gutterBottom>
        Import Data
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Upload Excel (.xlsx) files to bulk-import environments or systems. Duplicate names are
        skipped automatically.
      </Typography>

      <Divider sx={{ mb: 3 }} />

      <ImportSection
        title="Import Environments"
        onUpload={handleImportEnvironments}
        loading={activeSection === 'environments' && importLoading}
        result={activeSection === 'environments' ? lastImportResult : null}
        error={activeSection === 'environments' ? importError : null}
      />

      <ImportSection
        title="Import Systems"
        onUpload={handleImportSystems}
        loading={activeSection === 'systems' && importLoading}
        result={activeSection === 'systems' ? lastImportResult : null}
        error={activeSection === 'systems' ? importError : null}
      />
    </Box>
  );
}
