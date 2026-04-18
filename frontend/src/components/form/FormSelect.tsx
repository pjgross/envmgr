import { ReactNode } from 'react';
import { TextField, type TextFieldProps } from '@mui/material';
import { Controller, useFormContext, type FieldValues, type Path } from 'react-hook-form';

type FormSelectProps<TFields extends FieldValues> = Omit<
  TextFieldProps,
  'name' | 'select' | 'error' | 'helperText' | 'value' | 'onChange' | 'ref'
> & {
  name: Path<TFields>;
  helperText?: TextFieldProps['helperText'];
  children: ReactNode;
};

/**
 * MUI `<TextField select>`-style dropdown wired to react-hook-form.
 * Uses Controller so non-string values (numbers) round-trip correctly.
 */
export default function FormSelect<TFields extends FieldValues>({
  name,
  helperText,
  children,
  ...rest
}: FormSelectProps<TFields>) {
  const { control } = useFormContext<TFields>();

  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <TextField
          {...rest}
          select
          {...field}
          value={field.value ?? ''}
          error={Boolean(fieldState.error?.message)}
          helperText={fieldState.error?.message ?? helperText}
        >
          {children}
        </TextField>
      )}
    />
  );
}
