import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { breadcrumbsFor } from '../components/layout/routeMeta';

const APP = 'EnvManager';

/**
 * Sets document.title from the route's breadcrumb trail, innermost first:
 * "Naming policy · Administration · EnvManager".
 *
 * `override` is how a DETAIL page contributes its entity's name — the one
 * piece of a title no static table can hold (spec §6): ROUTE_META is static
 * and unit-testable, and a fetched entity name never belongs in it.
 */
export function usePageTitle(override?: string): void {
  const { pathname } = useLocation();
  useEffect(() => {
    const crumbs = breadcrumbsFor(pathname).map((c) => c.label).reverse();
    const parts = override ? [override, ...crumbs.slice(1)] : crumbs;
    document.title = [...parts, APP].join(' · ');
    return () => {
      document.title = APP;
    };
  }, [pathname, override]);
}
