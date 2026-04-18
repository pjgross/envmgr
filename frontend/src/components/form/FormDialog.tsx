import { ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  type DialogProps,
} from '@mui/material';
import { FormProvider, type UseFormReturn, type FieldValues } from 'react-hook-form';

interface FormDialogProps<
  TFields extends FieldValues,
  TContext = unknown,
  TTransformedValues extends FieldValues = TFields,
> extends Omit<DialogProps, 'onSubmit' | 'onClose' | 'title'> {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  form: UseFormReturn<TFields, TContext, TTransformedValues>;
  onSubmit: (values: TTransformedValues) => void | Promise<void>;
  submitLabel?: string;
  cancelLabel?: string;
  submittingLabel?: string;
  children: ReactNode;
}

export default function FormDialog<
  TFields extends FieldValues,
  TContext = unknown,
  TTransformedValues extends FieldValues = TFields,
>({
  open,
  onClose,
  title,
  form,
  onSubmit,
  submitLabel = 'Save',
  cancelLabel = 'Cancel',
  submittingLabel,
  children,
  maxWidth = 'sm',
  fullWidth = true,
  ...dialogProps
}: FormDialogProps<TFields, TContext, TTransformedValues>) {
  const submitting = form.formState.isSubmitting;

  const handleSubmit = form.handleSubmit(async (values) => {
    await onSubmit(values);
  });

  return (
    <Dialog
      open={open}
      onClose={submitting ? undefined : onClose}
      maxWidth={maxWidth}
      fullWidth={fullWidth}
      {...dialogProps}
    >
      <FormProvider {...form}>
        <form onSubmit={handleSubmit} noValidate>
          <DialogTitle>{title}</DialogTitle>
          <DialogContent>{children}</DialogContent>
          <DialogActions>
            <Button onClick={onClose} disabled={submitting}>
              {cancelLabel}
            </Button>
            <Button type="submit" variant="contained" disabled={submitting}>
              {submitting ? (submittingLabel ?? `${submitLabel}...`) : submitLabel}
            </Button>
          </DialogActions>
        </form>
      </FormProvider>
    </Dialog>
  );
}
