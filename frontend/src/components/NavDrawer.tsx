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

function splitPathAndQuery(value: string): [pathname: string, search: string] {
  const qIndex = value.indexOf('?');
  return qIndex === -1 ? [value, ''] : [value.slice(0, qIndex), value.slice(qIndex + 1)];
}

/**
 * `path` (a nav item's declared destination) is active for `current` (the
 * browser's actual URL) when the pathname matches as before — equal, or
 * `current` nested one level under `path` — AND every query param `path`
 * itself declares is present with the same value on `current`.
 *
 * This is a QUERY-SUBSET match, deliberately not full-URL equality: an admin
 * entity-config item's path carries `?tab=<key>` (§6), so equality is right
 * for telling two tabs on the same entity apart (`?tab=gate-types` must not
 * light up for `?tab=fields`) — but a plain item with no query in its own
 * path (e.g. `/environment-requests`) must still match when the page itself
 * has written an unrelated param into the URL (that list writes its
 * resolved default sort back on mount). Full-URL equality would mean that
 * page's drawer item never highlights — the exact false negative a resolved
 * default-sort mismatch produced in navRoutes.test.tsx before it was fixed
 * to compare on the same subset principle.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function isPathActive(current: string, path: string): boolean {
  const [currentPathname, currentSearch] = splitPathAndQuery(current);
  const [pathPathname, pathSearch] = splitPathAndQuery(path);
  const pathnameMatches =
    currentPathname === pathPathname || currentPathname.startsWith(pathPathname + '/');
  if (!pathnameMatches) return false;
  const requiredParams = new URLSearchParams(pathSearch);
  if ([...requiredParams.keys()].length === 0) return true;
  const currentParams = new URLSearchParams(currentSearch);
  for (const [key, value] of requiredParams) {
    if (currentParams.get(key) !== value) return false;
  }
  return true;
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
      sx={{ ...itemSx, pl: nested ? 3 : 2 }}
    >
      {item.icon !== undefined && <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>}
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
