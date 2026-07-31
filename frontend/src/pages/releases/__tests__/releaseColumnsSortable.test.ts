import { describe, expect, it } from 'vitest';
import { releaseColumns } from '../releaseColumns';
import { isSortable } from '../../../hooks/serverGridParams';

describe('release grid columns', () => {
  it('marks exactly the whitelisted columns sortable', () => {
    releaseColumns.forEach((col) => {
      // DataGrid treats an omitted `sortable` as true.
      const declared = col.sortable ?? true;
      expect({ field: col.field, sortable: declared }).toEqual({
        field: col.field,
        sortable: isSortable('releases', col.field),
      });
    });
  });

  it('covers the computed columns that lose sorting', () => {
    const computed = ['phase_count', 'scope_count', 'scope_change_count', 'blocker_count', 'systems'];
    computed.forEach((field) => {
      const col = releaseColumns.find((c) => c.field === field);
      expect(col, `${field} column missing`).toBeDefined();
      expect(col?.sortable).toBe(false);
    });
  });
});
