import { act, renderHook } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useServerGrid } from '../useServerGrid';

function wrapper(initialEntries: string[]) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
  );
}

function setup(url = '/releases') {
  const onFetch = vi.fn();
  const hook = renderHook(
    () => useServerGrid({ endpoint: 'releases', filterKeys: ['status'], onFetch }),
    { wrapper: wrapper([url]) }
  );
  return { ...hook, onFetch };
}

describe('useServerGrid', () => {
  it('fetches the endpoint default sort on mount', () => {
    const { onFetch } = setup();
    expect(onFetch).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 25, offset: 0, sort_by: 'created_at', sort_dir: 'desc' })
    );
  });

  it('restores page, sort and filters from the URL', () => {
    const { result } = setup('/releases?page=2&page_size=50&sort_by=name&sort_dir=asc&status=draft');
    expect(result.current.paginationModel).toEqual({ page: 2, pageSize: 50 });
    expect(result.current.sortModel).toEqual([{ field: 'name', sort: 'asc' }]);
    expect(result.current.filters.status).toBe('draft');
  });

  it('never sends a sort_by outside the whitelist, even from a URL', () => {
    const { onFetch } = setup('/releases?sort_by=phase_count');
    expect(onFetch).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'created_at' })
    );
    expect(onFetch).not.toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'phase_count' })
    );
  });

  it('resets to page 0 when a filter changes', () => {
    const { result, onFetch } = setup('/releases?page=3');
    onFetch.mockClear();
    act(() => result.current.setFilter('status', 'draft'));
    expect(result.current.paginationModel.page).toBe(0);
    expect(onFetch).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 }));
  });

  it('resets to page 0 when the sort changes', () => {
    const { result, onFetch } = setup('/releases?page=3');
    onFetch.mockClear();
    act(() => result.current.onSortModelChange([{ field: 'name', sort: 'asc' }]));
    expect(result.current.paginationModel.page).toBe(0);
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 0, sort_by: 'name', sort_dir: 'asc' })
    );
  });

  it('falls back to the default sort when the grid clears the sort model', () => {
    const { result, onFetch } = setup();
    onFetch.mockClear();
    act(() => result.current.onSortModelChange([]));
    expect(onFetch).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort_by: 'created_at', sort_dir: 'desc' })
    );
  });
});
