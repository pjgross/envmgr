import { useCallback, useRef, useState } from 'react';
import ConfirmDialog, { ConfirmDialogProps } from '../components/ConfirmDialog';

type ConfirmOpts = Omit<ConfirmDialogProps, 'open' | 'onConfirm' | 'onCancel'>;

/**
 * Promise-based MUI confirmation dialog hook.
 *
 * Usage:
 *   const { confirm, dialog } = useConfirm();
 *   const handleDelete = async () => {
 *     if (!(await confirm({ message: 'Delete this item?', destructive: true }))) return;
 *     // ...do the delete
 *   };
 *   return <>{...ui}{dialog}</>;
 *
 * Render `dialog` once anywhere in the component tree. Each `confirm(opts)` call
 * returns a Promise that resolves true/false based on the user's choice.
 */
export function useConfirm() {
  const [state, setState] = useState<{ opts: ConfirmOpts } | null>(null);
  const resolveRef = useRef<((result: boolean) => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOpts): Promise<boolean> => {
    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setState({ opts });
    });
  }, []);

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false);
    resolveRef.current = null;
    setState(null);
  }, []);

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true);
    resolveRef.current = null;
    setState(null);
  }, []);

  const dialog = (
    <ConfirmDialog
      open={state !== null}
      onCancel={handleCancel}
      onConfirm={handleConfirm}
      message={state?.opts.message ?? ''}
      title={state?.opts.title}
      confirmLabel={state?.opts.confirmLabel}
      cancelLabel={state?.opts.cancelLabel}
      destructive={state?.opts.destructive}
    />
  );

  return { confirm, dialog };
}
