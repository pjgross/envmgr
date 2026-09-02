import type { ReactNode } from 'react';
import {
  Collapse,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
} from '@mui/material';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { isNavGroup, type NavEntry, type NavItem } from './navConfig';

// eslint-disable-next-line react-refresh/only-export-components
export function isPathActive(current: string, path: string): boolean {
  return current === path || current.startsWith(path + '/');
}

function allItems(entries: NavEntry[]): NavItem[] {
  return entries.flatMap((e) => (isNavGroup(e) ? e.children : [e]));
}

/** Longest matching path wins, so `/releases` and `/releases/calendar` never light together. */
// eslint-disable-next-line react-refresh/only-export-components
export function activeItemPath(entries: NavEntry[], current: string): string | undefined {
  let best: string | undefined;
  for (const item of allItems(entries)) {
    if (isPathActive(current, item.path) && (best === undefined || item.path.length > best.length)) {
      best = item.path;
    }
  }
  return best;
}

/** Label of the group holding the active item, or undefined. */
// eslint-disable-next-line react-refresh/only-export-components
export function groupContaining(entries: NavEntry[], current: string): string | undefined {
  const active = activeItemPath(entries, current);
  if (active === undefined) return undefined;
  for (const entry of entries) {
    if (isNavGroup(entry) && entry.children.some((c) => c.path === active)) return entry.label;
  }
  return undefined;
}

export interface NavDrawerProps {
  entries: NavEntry[];
  currentPath: string;
  isGroupOpen: (label: string) => boolean;
  onToggleGroup: (label: string) => void;
  onNavigate: (path: string) => void;
  /** Rendered above the list — admin mode's back link and heading. */
  header?: ReactNode;
}

const itemSx = { borderRadius: 1, mx: 1, mb: 0.5 };

export default function NavDrawer({
  entries,
  currentPath,
  isGroupOpen,
  onToggleGroup,
  onNavigate,
  header,
}: NavDrawerProps) {
  const active = activeItemPath(entries, currentPath);

  const renderItem = (item: NavItem, nested: boolean) => (
    <ListItemButton
      key={item.path}
      selected={item.path === active}
      onClick={() => onNavigate(item.path)}
      sx={{ ...itemSx, pl: nested ? 4 : 2 }}
    >
      {item.icon !== undefined && <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>}
      <ListItemText primary={item.label} />
    </ListItemButton>
  );

  return (
    <>
      {header}
      <List dense>
        {entries.map((entry) => {
          if (!isNavGroup(entry)) return renderItem(entry, false);
          const open = isGroupOpen(entry.label);
          return (
            <div key={entry.label}>
              <ListItemButton
                onClick={() => onToggleGroup(entry.label)}
                aria-expanded={open}
                sx={itemSx}
              >
                <ListItemIcon sx={{ minWidth: 36 }}>{entry.icon}</ListItemIcon>
                <ListItemText primary={entry.label} primaryTypographyProps={{ noWrap: true }} />
                {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
              </ListItemButton>
              <Collapse in={open} timeout="auto" unmountOnExit>
                <List dense disablePadding>
                  {entry.children.map((child) => renderItem(child, true))}
                </List>
              </Collapse>
            </div>
          );
        })}
      </List>
    </>
  );
}
