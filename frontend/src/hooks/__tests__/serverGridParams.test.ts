import { describe, expect, it } from 'vitest';
import { buildParams, isSortable, resolveSort } from '../serverGridParams';

describe('resolveSort', () => {
  it('keeps a whitelisted field', () => {
    expect(resolveSort('releases', 'name', 'asc')).toEqual({ sort_by: 'name', sort_dir: 'asc' });
  });

  it('falls back to the endpoint default for a field outside the whitelist', () => {
    // A bookmarked ?sort_by=phase_count must never reach the server: it is a 422.
    expect(resolveSort('releases', 'phase_count', 'asc')).toEqual({
      sort_by: 'created_at',
      sort_dir: 'asc',
    });
  });

  it('always returns a direction, even when none was supplied', () => {
    // sorting() applies an endpoint-wide default_dir when sort_dir is omitted,
    // so releases would resolve to desc. The direction is never left implicit.
    expect(resolveSort('releases', 'name', null)).toEqual({
      sort_by: 'name',
      sort_dir: 'desc',
    });
    expect(resolveSort('environments', 'name', null)).toEqual({
      sort_by: 'name',
      sort_dir: 'asc',
    });
  });

  it('ignores a junk direction', () => {
    expect(resolveSort('releases', 'name', 'sideways').sort_dir).toBe('desc');
  });
});

describe('isSortable', () => {
  it('is true for whitelisted fields and false for computed ones', () => {
    expect(isSortable('releases', 'target_date')).toBe(true);
    expect(isSortable('releases', 'phase_count')).toBe(false);
    expect(isSortable('releases', 'systems')).toBe(false);
    expect(isSortable('releases', 'id')).toBe(false);
  });
});

describe('buildParams', () => {
  it('translates page/pageSize into limit/offset', () => {
    const p = buildParams({
      endpoint: 'releases',
      page: 2,
      pageSize: 25,
      sortBy: 'name',
      sortDir: 'asc',
      filters: {},
    });
    expect(p.limit).toBe(25);
    expect(p.offset).toBe(50);
  });

  it('always includes both sort parameters', () => {
    const p = buildParams({
      endpoint: 'releases',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: {},
    });
    expect(p.sort_by).toBe('created_at');
    expect(p.sort_dir).toBe('desc');
  });

  it("omits the pages' no-filter sentinels", () => {
    const p = buildParams({
      endpoint: 'releases',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { status: 'all', release_type: '', system_id: '3' },
    });
    expect(p).not.toHaveProperty('status');
    expect(p).not.toHaveProperty('release_type');
    expect(p.system_id).toBe('3');
  });

  it('does not let a filter key override the resolved sort/paging params', () => {
    // A filters object containing sort_by/sort_dir/limit (e.g. relayed from a
    // careless caller) must not clobber the values resolveSort/pageSize computed.
    const p = buildParams({
      endpoint: 'releases',
      page: 0,
      pageSize: 25,
      sortBy: 'name',
      sortDir: 'asc',
      filters: { sort_by: 'phase_count', sort_dir: 'sideways', limit: '999' },
    });
    expect(p.sort_by).toBe('name');
    expect(p.sort_dir).toBe('asc');
    expect(p.limit).toBe(25);
  });

  it('keeps the literal text "all" typed into a free-text filter', () => {
    // The sentinel means "no selection" for a select. In a text box it is a
    // search term, and dropping it returns unfiltered results while the box
    // still reads "all" — a wrong answer presented as a filtered one.
    const p = buildParams({
      endpoint: 'systems',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { search: 'all' },
      textKeys: ['search'],
    });
    expect(p.search).toBe('all');
  });

  it('still drops "all" from a select on a page that also has a text filter', () => {
    const p = buildParams({
      endpoint: 'environments',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { status: 'all', search: 'all' },
      textKeys: ['search'],
    });
    expect(p).not.toHaveProperty('status');
    expect(p.search).toBe('all');
  });

  it('drops an empty text filter, which means the box is simply empty', () => {
    const p = buildParams({
      endpoint: 'systems',
      page: 0,
      pageSize: 25,
      sortBy: null,
      sortDir: null,
      filters: { search: '' },
      textKeys: ['search'],
    });
    expect(p).not.toHaveProperty('search');
  });
});
