import { TextField, type TextFieldProps } from '@mui/material';
import { useFormContext, type RegisterOptions, type FieldValues, type Path } from 'react-hook-form';

type FormTextFieldProps<TFields extends FieldValues> = Omit<
  TextFieldProps,
  'name' | 'error' | 'helperText' | 'value' | 'onChange' | 'onBlur' | 'ref'
> & {
  name: Path<TFields>;
  rules?: RegisterOptions<TFields, Path<TFields>>;
  helperText?: TextFieldProps['helperText'];
};

export default function FormTextField<TFields extends FieldValues>({
  name,
  rules,
  helperText,
  ...rest
}: FormTextFieldProps<TFields>) {
  const {
    register,
    formState: { errors },
  } = useFormContext<TFields>();

  const errorMessage = (errors[name]?.message as string | undefined) ?? undefined;

  return (
    <TextField
      {...rest}
      {...register(name, rules)}
      error={Boolean(errorMessage)}
      helperText={errorMessage ?? helperText}
    />
  );
}
