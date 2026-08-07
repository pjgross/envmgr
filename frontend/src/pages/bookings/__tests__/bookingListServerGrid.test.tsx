import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingList, { apiProjectId, bookingColumns, buildCustomFieldColumns } from '../BookingList';

// No HTTP — this test is about the wiring between the URL/filters and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    listBookings: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
    getAllowedTransitions: vi.fn().mockResolvedValue([]),
  },
}));

// Also unmocked-network-free: BookingList fetches custom field definitions on
// mount alongside the booking page itself.
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn().mockResolvedValue([]),
  },
}));

// And the Project filter's own picker source — useAllProjects, which calls
// projectService.listProjects({ is_active: true }).
vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi
      .fn()
      .mockResolvedValue({ rows: [{ id: 3, name: 'Mortgage' }], total: 1 }),
  },
}));

import { bookingService } from '../../../services/bookingService';
import { projectService } from '../../../services/projectService';
import type { CustomFieldDefinition } from '../../../types/customField';

function renderBookingList(url = '/bookings') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[url]}>
        <BookingList />
      </MemoryRouter>
    </Provider>
  );
}

function lastListParams() {
  const calls = vi.mocked(bookingService.listBookings).mock.calls;
  return calls[calls.length - 1]?.[0];
}

describe('BookingList server-side grid', () => {
  it('sends paging, sorting and the wire-named status filter', async () => {
    renderBookingList('/bookings?page=2&sort_by=end_date&sort_dir=desc&booking_status=approved');

    await waitFor(() => expect(lastListParams()).toMatchObject({
      limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved',
    }));
  });

  it('marks joined and computed columns unsortable', () => {
    // GET /bookings/ whitelists start_date, end_date and status only.
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));

    expect(byField.start_date.sortable).not.toBe(false);
    expect(byField.end_date.sortable).not.toBe(false);
    expect(byField.status.sortable).not.toBe(false);

    [
      'project_name',
      'project_name_link',
      'environment_name',
      'booked_by_username',
      'booking_type_id',
      'conflicts',
      'actions',
    ].forEach((field) => expect(byField[field].sortable).toBe(false));
  });

  it('reads the Project column from project_name_link and the Purpose column from project_name, never swapped', () => {
    // The two are different values on the same row — project_name is the
    // free-text "Purpose" field, project_name_link is the linked project's
    // resolved name. A row where they visibly differ pins that neither
    // column reads the other's field.
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));
    const row = {
      id: 1,
      project_name: 'Regression sweep',
      project_name_link: 'Mortgage',
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const purposeCell = byField.project_name.renderCell?.({ row } as any) as any;
    expect(purposeCell.props.children).toBe('Regression sweep');

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const projectValue = (byField.project_name_link.valueGetter as any)({ row });
    expect(projectValue).toBe('Mortgage');
  });

  it('marks the Project column unsortable (resolved by a batch lookup, not a whitelisted column)', () => {
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));
    expect(byField.project_name_link.sortable).toBe(false);
  });

  it('dispatches the list fetch with the selected project id and a reset offset', async () => {
    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/bookings?page=2']}>
          <BookingList />
        </MemoryRouter>
      </Provider>
    );

    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    vi.mocked(bookingService.listBookings).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    const option = await screen.findByRole('option', { name: 'Mortgage' });
    await userEvent.click(option);

    await waitFor(() =>
      expect(bookingService.listBookings).toHaveBeenLastCalledWith(
        expect.objectContaining({ project_id: 3, offset: 0 })
      )
    );
  });

  // Finding 4: fetching every project rather than only active ones would
  // offer archived projects as filter choices. Nothing else in this suite
  // inspects the call params, so dropping `is_active: true` here previously
  // left every test green.
  it('fetches only active projects for the Project filter (drops is_active: true otherwise)', async () => {
    renderBookingList();
    await waitFor(() =>
      expect(projectService.listProjects).toHaveBeenCalledWith(
        expect.objectContaining({ is_active: true })
      )
    );
  });

  // Finding 2: a bookmarked/shared link, or a colleague's project archived
  // out from under an open tab, leaves `project_id` in the URL pointing at a
  // project no longer in the active list. The grid stays filtered to it (see
  // apiProjectId below) but the old code rendered no matching MenuItem, so
  // the select showed blank — and, combined with `disabled={projects.length
  // === 0}`, was sometimes impossible to clear without hand-editing the URL.
  it('keeps a project_id filter not in the active list visible and clearable', async () => {
    renderBookingList('/bookings?project_id=9');
    await waitFor(() => expect(lastListParams()).toBeDefined());

    const combobox = await screen.findByRole('combobox', { name: 'Project' });
    expect(combobox).toHaveTextContent('Project #9 (unavailable)');
    expect(combobox).not.toHaveAttribute('aria-disabled', 'true');

    await userEvent.click(combobox);
    await userEvent.click(await screen.findByRole('option', { name: 'All projects' }));

    await waitFor(() => expect(lastListParams()?.project_id).toBeUndefined());
  });

  it('does not disable the Project select when the active list is empty but a filter is set', async () => {
    // Every project archived, or the picker fetch failed — either way
    // `projects` comes back empty while the URL still names one.
    vi.mocked(projectService.listProjects).mockResolvedValueOnce({ rows: [], total: 0 });
    renderBookingList('/bookings?project_id=9');
    await waitFor(() => expect(projectService.listProjects).toHaveBeenCalled());

    const combobox = await screen.findByRole('combobox', { name: 'Project' });
    expect(combobox).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('spells the project filter\'s "no selection" state `any`, never `all` (buildParams sentinel collision)', async () => {
    // `all` is buildParams' own "no selection" sentinel and is dropped before
    // a request is built — two states of the toggle would collapse to
    // byte-identical params and the grid would never refetch. See
    // ReleaseList's identical guard.
    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/bookings']}>
          <BookingList />
        </MemoryRouter>
      </Provider>
    );
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    const allOption = await screen.findByRole('option', { name: 'All projects' });
    expect(allOption).toHaveAttribute('data-value', 'any');
  });

  it('disables the column filter, which would filter only the loaded page', async () => {
    // Raw DataGrid gates the column-menu Filter item on this prop alone, not
    // on whether a toolbar is rendered. Without it the menu filters the 25
    // loaded rows while the footer shows the server total.
    //
    // The menu-icon button is only revealed by CSS on hover in a real
    // browser, so jsdom's computed style hides it from `getAllByRole`'s
    // accessible-name matching (an element the name algorithm treats as
    // hidden resolves to an empty accessible name, which a `name` matcher
    // can never match) even with `hidden: true`. Find it by its `aria-label`
    // attribute directly instead — `hidden: true` still gets it into the
    // query's search space at all, which is what matters here.
    renderBookingList();
    await waitFor(() => expect(lastListParams()).toBeDefined());

    const menuButtons = screen
      .getAllByRole('button', { hidden: true })
      .filter((b) => b.getAttribute('aria-label') === 'Menu');
    expect(menuButtons.length).toBeGreaterThan(0);
    fireEvent.click(menuButtons[0]);

    const menu = await screen.findByRole('menu', { hidden: true });
    const filterItem = within(menu)
      .getAllByRole('menuitem', { hidden: true })
      .find((item) => /filter/i.test(item.textContent ?? ''));
    expect(filterItem).toBeUndefined();
  });

  it('marks per-tenant custom-field columns unsortable, since none is in the backend whitelist', () => {
    // Unlike bookingColumns above, these columns are built at render time
    // from the tenant's custom field definitions, so the static column-list
    // test above can't see them. @mui/x-data-grid virtualizes columns by
    // container width, and jsdom reports zero layout width, so a real render
    // here only ever puts the first few static columns in the DOM — there is
    // no way to scroll a custom-field column into view to inspect its
    // header. `buildCustomFieldColumns` is exported from BookingList for
    // exactly this reason: assert on the GridColDef it produces directly,
    // the same way the static columns are asserted on above.
    const def: CustomFieldDefinition = {
      id: 1,
      tenant_id: 1,
      entity_type: 'booking',
      entity_subtype: null,
      field_key: 'severity',
      label: 'Severity',
      field_type: 'text',
      required: false,
      display_order: 1,
      options: null,
      lifecycle_states: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };

    const [column] = buildCustomFieldColumns([def]);

    // Namespaced (`cf_${field_key}`), not the raw key — see the collision
    // test below. `headerName` is untouched, since that's what users see.
    expect(column.field).toBe('cf_severity');
    expect(column.headerName).toBe('Severity');
    expect(column.sortable).toBe(false);
  });

  it('never generates a custom-field column whose field collides with a static one', () => {
    // The bug this guards is the one EnvironmentList already hit: a tenant
    // custom field keyed the same as a static column gives two GridColDefs
    // one `field`, which MUI treats as a single column — duplicate headers,
    // and a visibility toggle on one silently hides the other. `saveColumnModel`
    // below then persists the spurious visibility change, so the real column
    // stays hidden across reloads. No fixture defines a colliding custom
    // field, so nothing else in this suite can catch it.
    const staticFields = new Set(bookingColumns.map((c) => c.field));

    const defs: CustomFieldDefinition[] = [...staticFields, 'severity'].map((key, i) => ({
      id: i + 1,
      tenant_id: 1,
      entity_type: 'booking',
      entity_subtype: null,
      field_key: key,
      label: key,
      field_type: 'text',
      required: false,
      display_order: i,
      options: null,
      lifecycle_states: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }));

    const customCols = buildCustomFieldColumns(defs);
    expect(customCols).toHaveLength(defs.length);
    customCols.forEach((col) => expect(staticFields.has(col.field)).toBe(false));
    // And they don't collide with each other either.
    expect(new Set(customCols.map((c) => c.field)).size).toBe(customCols.length);
  });

  it('still reads the value from the raw field_key, not the namespaced column id', () => {
    // The namespace is a grid-column concern only. `custom_fields` on the row
    // is keyed by the tenant's own field_key, so a valueGetter that looked up
    // `cf_severity` would render every custom cell as '—' — the column would
    // be present, correctly named, and permanently empty.
    const def: CustomFieldDefinition = {
      id: 1,
      tenant_id: 1,
      entity_type: 'booking',
      entity_subtype: null,
      field_key: 'severity',
      label: 'Severity',
      field_type: 'text',
      required: false,
      display_order: 1,
      options: null,
      lifecycle_states: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };

    const [column] = buildCustomFieldColumns([def]);
    const row = { custom_fields: { severity: 'high' } };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((column.valueGetter as any)({ row })).toBe('high');
  });
});

describe('apiProjectId', () => {
  it('treats "any" as no filter, not a value to send to the server', () => {
    expect(apiProjectId('any')).toBeUndefined();
  });

  it('treats an absent filter as no filter', () => {
    expect(apiProjectId(undefined)).toBeUndefined();
  });

  it('passes a chosen project id through as a number', () => {
    expect(apiProjectId('7')).toBe(7);
    expect(apiProjectId(7)).toBe(7);
  });
});
