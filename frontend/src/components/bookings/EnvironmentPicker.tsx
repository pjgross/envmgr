import { Autocomplete, Chip, TextField } from '@mui/material';
import type { Environment } from '../../types/environment';

type Props = {
  environments: Environment[];
  value: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
  label?: string;
};

export default function EnvironmentPicker({
  environments,
  value,
  onChange,
  disabled,
  label = 'Environments',
}: Props) {
  const selected = environments.filter((e) => value.includes(e.id));
  return (
    <Autocomplete
      multiple
      size="small"
      disabled={disabled}
      options={environments}
      getOptionLabel={(e) => e.name}
      value={selected}
      onChange={(_, next) => onChange(next.map((e) => e.id))}
      renderTags={(vals, getTagProps) =>
        vals.map((v, idx) => (
          <Chip label={v.name} size="small" {...getTagProps({ index: idx })} key={v.id} />
        ))
      }
      renderInput={(params) => <TextField {...params} label={label} />}
      isOptionEqualToValue={(o, v) => o.id === v.id}
    />
  );
}
