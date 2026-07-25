import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
  TextField,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import FilterListIcon from '@mui/icons-material/FilterList';
import { matchComponents, type SearchableComponent } from './topologyFocus';

const MAX_RESULTS = 20;

interface Props {
  components: SearchableComponent[];
  onSelect: (componentId: number) => void;
  availableTypes: string[];
  hiddenTypes: Set<string>;
  onToggleType: (type: string) => void;
}

export default function TopologyToolbar({
  components,
  onSelect,
  availableTypes,
  hiddenTypes,
  onToggleType,
}: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [typeAnchor, setTypeAnchor] = useState<null | HTMLElement>(null);

  const matches = useMemo(() => matchComponents(query, components), [query, components]);
  const visible = matches.slice(0, MAX_RESULTS);
  const overflow = matches.length - visible.length;

  const choose = (id: number) => {
    onSelect(id);
    setQuery('');
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false);
      setHighlight(0);
      return;
    }
    if (!open || visible.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, visible.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const item = visible[highlight];
      if (item) choose(item.id);
    }
  };

  return (
    <Box
      sx={{
        position: 'relative',
        p: 1,
        borderBottom: 1,
        borderColor: 'divider',
        display: 'flex',
        gap: 1,
        alignItems: 'flex-start',
      }}
    >
      <TextField
        size="small"
        fullWidth
        sx={{ flex: 1 }}
        placeholder="Search component…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          setHighlight(0);
        }}
        onFocus={() => query && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
        }}
        inputProps={{
          'aria-expanded': open && visible.length > 0,
          'aria-haspopup': 'listbox',
        }}
      />
      {open && visible.length > 0 && (
        <Paper
          sx={{ position: 'absolute', top: '100%', left: 8, right: 8, zIndex: 5, maxHeight: 260, overflow: 'auto' }}
        >
          <List dense disablePadding role="listbox">
            {visible.map((c, i) => (
              <ListItemButton
                key={c.id}
                role="option"
                aria-selected={i === highlight}
                selected={i === highlight}
                onClick={() => choose(c.id)}
              >
                <ListItemText primary={c.name} secondary={c.systemName} />
              </ListItemButton>
            ))}
          </List>
          {overflow > 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', px: 2, py: 0.5 }}>
              +{overflow} more — refine search
            </Typography>
          )}
        </Paper>
      )}
      {availableTypes.length > 0 && (
        <>
          <Button
            id="topology-types-btn"
            size="small"
            variant="outlined"
            startIcon={<FilterListIcon />}
            onClick={(e) => setTypeAnchor(e.currentTarget)}
            sx={{ flexShrink: 0, whiteSpace: 'nowrap', mt: 0.25 }}
          >
            {hiddenTypes.size > 0 ? `Types · ${hiddenTypes.size} hidden` : 'Types'}
          </Button>
          <Menu
            anchorEl={typeAnchor}
            open={Boolean(typeAnchor)}
            onClose={() => setTypeAnchor(null)}
            MenuListProps={{ 'aria-labelledby': 'topology-types-btn' }}
          >
            {availableTypes.map((t) => (
              <MenuItem
                key={t}
                dense
                role="menuitemcheckbox"
                aria-checked={!hiddenTypes.has(t)}
                onClick={() => onToggleType(t)}
              >
                <Checkbox
                  edge="start"
                  size="small"
                  checked={!hiddenTypes.has(t)}
                  tabIndex={-1}
                  disableRipple
                />
                <ListItemText primary={t.replace(/_/g, ' ')} />
              </MenuItem>
            ))}
          </Menu>
        </>
      )}
    </Box>
  );
}
