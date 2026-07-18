/**
 * ScopeImportDialog — import scope items from an .xlsx spreadsheet.
 *
 * Offers a template download, a file picker, and shows a result summary
 * (created / updated counts plus a small table of per-row errors).
 */
import { useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { releaseService } from '../../services/releaseService';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ScopeImportResult } from '../../types/releaseChange';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  onImported: () => void;
}

export default function ScopeImportDialog({ open, onClose, releaseId, onImported }: Props) {
  const snackbar = useSnackbar();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<ScopeImportResult | null>(null);

  const reset = () => {
    setFile(null);
    setResult(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleDownloadTemplate = async () => {
    setDownloading(true);
    try {
      await releaseService.downloadScopeImportTemplate();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to download template');
    } finally {
      setDownloading(false);
    }
  };

  const handleImport = async () => {
    if (!file) return;
    setSubmitting(true);
    setResult(null);
    try {
      const res = await releaseService.importScope(releaseId, file);
      setResult(res);
      if (res.errors.length === 0) {
        snackbar.success(`Imported ${res.created} created, ${res.updated} updated`);
      } else {
        snackbar.warning(`Imported with ${res.errors.length} row error(s)`);
      }
      onImported();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to import scope items');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Import Scope from Spreadsheet</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Upload an .xlsx file to create or update scope items in bulk. Start from
            the template to match the expected columns.
          </Typography>

          <Box>
            <Link
              component="button"
              type="button"
              onClick={handleDownloadTemplate}
              disabled={downloading}
              sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
            >
              <DownloadIcon fontSize="small" />
              Download template
            </Link>
          </Box>

          <Box>
            <Button
              variant="outlined"
              component="label"
              startIcon={<UploadFileIcon />}
              disabled={submitting}
            >
              Choose file
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                hidden
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setResult(null);
                }}
              />
            </Button>
            {file && (
              <Typography variant="body2" sx={{ mt: 1 }}>
                {file.name}
              </Typography>
            )}
          </Box>

          {result && (
            <Box>
              <Alert severity={result.errors.length ? 'warning' : 'success'} sx={{ mb: 1 }}>
                {result.created} created, {result.updated} updated
                {result.errors.length ? `, ${result.errors.length} error(s)` : ''}
              </Alert>
              {result.errors.length > 0 && (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Row</TableCell>
                      <TableCell>Field</TableCell>
                      <TableCell>Message</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {result.errors.map((e, i) => (
                      <TableRow key={`${e.row}-${e.field}-${i}`}>
                        <TableCell>{e.row}</TableCell>
                        <TableCell>{e.field}</TableCell>
                        <TableCell>{e.message}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Close
        </Button>
        <Button
          variant="contained"
          onClick={handleImport}
          disabled={!file || submitting}
        >
          Import
        </Button>
      </DialogActions>
    </Dialog>
  );
}
