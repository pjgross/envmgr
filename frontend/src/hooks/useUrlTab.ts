import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Which tab a page is on, held in `?tab=<key>` so it can be linked to and
 * survives a reload.
 *
 * `replace`, not `push`: clicking through five tabs then pressing Back should
 * leave the page, not walk back through the five tabs.
 *
 * An unknown key falls back to the default rather than rendering nothing — a
 * bookmark taken before a tab was renamed must still land somewhere.
 */
export function useUrlTab(
  keys: readonly string[],
  defaultKey: string,
  param = 'tab',
): [string, (key: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get(param);
  const tab = requested && keys.includes(requested) ? requested : defaultKey;

  const setTab = useCallback(
    (key: string) => {
      // Mutate a copy of the CURRENT params: other features own params on this
      // URL (ReleaseCalendar's ?phase=) and must survive a tab change.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set(param, key);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams, param],
  );

  return [tab, setTab];
}
