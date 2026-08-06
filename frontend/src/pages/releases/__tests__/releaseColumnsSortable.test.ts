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
    const computed = [
      'phase_count',
      'scope_count',
      'scope_change_count',
      'blocker_count',
      'overdue_criterion_count',
      'systems',
    ];
    computed.forEach((field) => {
      const col = releaseColumns.find((c) => c.field === field);
      expect(col, `${field} column missing`).toBeDefined();
      expect(col?.sortable).toBe(false);
    });
  });
});

describe('owning_project_name column', () => {
  it('renders the linked project name, not project_name (a different, external-tracker field)', () => {
    const column = releaseColumns.find((c) => c.field === 'owning_project_name');
    expect(column).toBeDefined();
    expect(column?.sortable).toBe(false);

    const rendered = column?.renderCell?.({
      row: { owning_project_name: 'Mortgage', owning_project_id: 3, project_name: 'wrong field' },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);
    expect(rendered).toBe('Mortgage');
  });

  it('renders a missing project as prose, not a blank cell', () => {
    const column = releaseColumns.find((c) => c.field === 'owning_project_name');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rendered = column?.renderCell?.({ row: { owning_project_name: null } } as any);
    expect(rendered).not.toBe(null);
    expect(rendered).not.toBe('');
  });
});
