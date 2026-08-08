import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import BookingList, {
  apiAgreementGap,
  apiProjectId,
  bookingColumns,
  buildCustomFieldColumns,
  groupDivergenceWarning,
} from '../BookingList';

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
import type { BookingResponse } from '../../../types/booking';
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

/**
 * Invoke a column's `renderCell` against a partial row and hand back the
 * element it produced, so its props can be asserted. @mui/x-data-grid
 * virtualizes columns and cells by container width and jsdom reports zero
 * layout width, so a real render of this page never gets these cells into the
 * DOM — every column test in this file asserts on the GridColDef directly.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
function renderColumnCell(col: any, row: Record<string, unknown>): any {
  return col.renderCell?.({ row } as any) as any;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

/** One list row, in an unacknowledged usage-agreement gap. */
function gapRow(id: number, gap: string): BookingResponse {
  return {
    id,
    environment_id: 10,
    environment_name: 'UAT-1',
    project_name: 'Regression sweep',
    project_id: 3,
    project_name_link: 'Mortgage',
    booked_by: 5,
    booked_by_username: 'sam',
    start_date: '2026-08-10T00:00:00Z',
    end_date: '2026-08-12T00:00:00Z',
    booking_type_id: 1,
    exclusive_use: false,
    status: 'approved',
    notes: null,
    recurrence_rule: null,
    recurrence_parent_id: null,
    release_id: null,
    test_phase_id: null,
    context_tag: 'none',
    custom_fields: null,
    tenant_id: 1,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    agreement_gap: gap,
    has_unacknowledged_agreement_gap: true,
    // Detail-only in value, null on every list row — see types/booking.ts.
    agreement_gap_ack: null,
    environment_group_id: null,
    environment_group_name: null,
  };
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
      'environment_group_name',
      'booked_by_username',
      'booking_type_id',
      'conflicts',
      // A3's gap column. `agreement_gap` is a FILTER on GET /bookings, never a
      // sort key — BOOKING_SORTS whitelists start_date, end_date and status
      // only, and an unknown sort_by is a 422, not a silent fallback.
      'agreement_gap',
      'actions',
    ].forEach((field) => expect(byField[field].sortable).toBe(false));
  });

  // Finding 3 (A2 whole-branch review): BookingList consumes
  // `BookingResponse`, which carries `environment_group_name`, but had no
  // column for it — the routine "work down the grid, approve each" journey
  // gave no on-screen sign a group existed, let alone that transitioning a
  // member here diverges it.
  it('renders a Group column reading environment_group_name, "—" when absent', () => {
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));
    expect(byField.environment_group_name).toBeDefined();
    expect(byField.environment_group_name.headerName).toBe('Group');

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const getter = byField.environment_group_name.valueGetter as any;
    expect(getter({ row: { environment_group_name: 'Checkout Squad' } })).toBe('Checkout Squad');
    expect(getter({ row: { environment_group_name: null } })).toBe('—');
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

  // --- A3 Task 6c: the usage-agreement gap column and filter ----------------

  it('renders the gap indicator from the row, and renders nothing for a covered booking', () => {
    // The column's renderCell is the JOIN between the row and the indicator —
    // both ends of it are tested (the indicator has its own suite, the wire
    // fields are pinned backend-side), and deleting the wiring between them is
    // exactly the shape that left 43 frontend tests green while the A2 repair
    // path regressed in full. @mui/x-data-grid virtualizes by container width
    // and jsdom reports zero width, so the cell never reaches the DOM in a real
    // render of this page — assert on the GridColDef directly, as every other
    // column test in this file does.
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));
    const col = byField.agreement_gap;
    expect(col).toBeDefined();
    expect(col.headerName).toBe('Agreement');

    const gap = 'Mortgage has no usage agreement for UAT-1';
    const inGap = renderColumnCell(col, {
      agreement_gap: gap,
      has_unacknowledged_agreement_gap: true,
    });
    expect(inGap.props.gap).toBe(gap);
    expect(inGap.props.hasUnacknowledgedGap).toBe(true);

    // Acknowledging is not resolving: the row is still in gap, and the flag is
    // what changed — both must reach the indicator, or the two states collapse.
    const acknowledged = renderColumnCell(col, {
      agreement_gap: gap,
      has_unacknowledged_agreement_gap: false,
    });
    expect(acknowledged.props.gap).toBe(gap);
    expect(acknowledged.props.hasUnacknowledgedGap).toBe(false);

    // Covered: the indicator itself renders nothing (its own suite pins that),
    // so the null gap must arrive as null rather than be papered over with a
    // '—' or a booking id.
    const covered = renderColumnCell(col, {
      agreement_gap: null,
      has_unacknowledged_agreement_gap: false,
    });
    expect(covered.props.gap).toBeNull();
  });

  it('reads the list column from agreement_gap, never the detail-only agreement_gap_ack', () => {
    // `agreement_gap_ack` is carried by GET /bookings/{id} alone — every LIST
    // row sends it as null, key present. A column that decided anything from it
    // would be present, correctly named and permanently wrong: every row would
    // read as unacknowledged, or as covered, depending which way it leaned.
    const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));
    const gap = 'Mortgage has no usage agreement for UAT-1';

    // A real list row: in gap, acknowledged, and `agreement_gap_ack: null`
    // because the list never carries it. The acknowledged state must still come
    // through, from the flag alone.
    const listRow = renderColumnCell(byField.agreement_gap, {
      agreement_gap: gap,
      has_unacknowledged_agreement_gap: false,
      agreement_gap_ack: null,
    });
    expect(listRow.props.gap).toBe(gap);
    expect(listRow.props.hasUnacknowledgedGap).toBe(false);

    // And an ack present alongside no gap never conjures one.
    const covered = renderColumnCell(byField.agreement_gap, {
      agreement_gap: null,
      has_unacknowledged_agreement_gap: false,
      agreement_gap_ack: {
        acknowledged_by_username: 'sam',
        acknowledged_at: '2026-08-08T00:00:00Z',
      },
    });
    expect(covered.props.gap).toBeNull();
  });

  it('sends agreement_gap=true when the gap filter selects bookings in gap', async () => {
    renderBookingList('/bookings?page=2');
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    vi.mocked(bookingService.listBookings).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Usage agreement' }));
    await userEvent.click(await screen.findByRole('option', { name: 'In gap' }));

    // The wire name is `agreement_gap`, exactly as declared by
    // `list_bookings` in backend/app/api/v1/bookings.py. FastAPI drops unknown
    // query params silently, so a misspelling here would filter nothing at all
    // and look entirely correct — /releases/calendar's `from`/`to` and the
    // Projects grid's `?project_id=` both shipped that way.
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ agreement_gap: true, offset: 0 })
    );
  });

  it('sends agreement_gap=false for the complement', async () => {
    renderBookingList();
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    vi.mocked(bookingService.listBookings).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Usage agreement' }));
    await userEvent.click(await screen.findByRole('option', { name: 'No gap' }));

    // Not the same as omitting it: `false` is the exact complement — covered
    // bookings AND those whose request names no project.
    await waitFor(() => expect(lastListParams()?.agreement_gap).toBe(false));
  });

  it('applies the gap filter straight from the URL', async () => {
    renderBookingList('/bookings?agreement_gap=true');
    await waitFor(() => expect(lastListParams()?.agreement_gap).toBe(true));
  });

  it('drops agreement_gap entirely when the filter is cleared, and refetches', async () => {
    renderBookingList('/bookings?agreement_gap=true');
    await waitFor(() => expect(lastListParams()?.agreement_gap).toBe(true));
    vi.mocked(bookingService.listBookings).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Usage agreement' }));
    await userEvent.click(await screen.findByRole('option', { name: 'All bookings' }));

    // A new request, not a silently-identical one: the grid's fetch effect is
    // keyed on the resolved params, so a "no selection" value that buildParams
    // already drops in the *other* state would leave both toggle states
    // byte-identical and nothing would ever be re-issued.
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());
    // Never `''` (a 422 from FastAPI's Optional[bool]) and never `'all'`.
    expect(lastListParams()?.agreement_gap).toBeUndefined();
    // And the select shows the cleared state rather than going blank — the
    // symptom of a "no selection" value that matches no MenuItem.
    expect(screen.getByRole('combobox', { name: 'Usage agreement' })).toHaveTextContent(
      'All bookings'
    );
  });

  it("spells the gap filter's \"no selection\" state `any`, never `all`", async () => {
    // `all` is buildParams' own "no selection" sentinel — see the identical
    // guard on the Project filter below, and ScopeWindowsTable, where two
    // toggle states built byte-identical params and the grid never refetched.
    // `''` is out for a different reason: MUI's Select renders it as a blank
    // box rather than as its own option's label.
    renderBookingList();
    await waitFor(() => expect(bookingService.listBookings).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('combobox', { name: 'Usage agreement' }));
    const noSelection = await screen.findByRole('option', { name: 'All bookings' });
    expect(noSelection).toHaveAttribute('data-value', 'any');
  });

  it('reads an unparseable gap value in the URL as no filter, in the select and on the wire alike', async () => {
    // A hand-edited or stale link. The two must agree: a select showing "All
    // bookings" over a grid filtered by something else — or a 422 that blanks
    // the grid entirely — are both worse than ignoring the value.
    renderBookingList('/bookings?agreement_gap=yes');

    await waitFor(() => expect(lastListParams()).toBeDefined());
    expect(lastListParams()?.agreement_gap).toBeUndefined();
    expect(screen.getByRole('combobox', { name: 'Usage agreement' })).toHaveTextContent(
      'All bookings'
    );
  });

  it('leaves booking creation available while a gap is on screen — A3 warns, it never blocks', async () => {
    // The frontend twin of `test_an_agreement_changes_no_booking_behaviour`.
    // A page of bookings every one of which is in an unacknowledged gap must
    // still offer every action it offers otherwise; gating "+ New Booking" (or
    // anything else) on a gap is the one thing A3 promised never to do.
    vi.mocked(bookingService.listBookings).mockResolvedValueOnce({
      rows: [
        gapRow(1, 'Mortgage has no usage agreement for UAT-1'),
        gapRow(2, "Mortgage's booking falls outside its agreed window for UAT-2"),
      ],
      total: 2,
    });
    renderBookingList();
    await waitFor(() => expect(lastListParams()).toBeDefined());

    expect(await screen.findByRole('button', { name: '+ New Booking' })).toBeEnabled();
  });

  it('takes the row count from X-Total-Count, not the length of the page', async () => {
    // The page holds one row; the server says there are 137. A grid that
    // counted its own rows would report a single page and hide the other 136 —
    // and the gap filter above would look like it had matched almost nothing.
    vi.mocked(bookingService.listBookings).mockResolvedValueOnce({
      rows: [gapRow(1, 'Mortgage has no usage agreement for UAT-1')],
      total: 137,
    });
    renderBookingList();

    expect(await screen.findByText(/of 137/)).toBeInTheDocument();
  });

  // Finding 3 (A2 whole-branch review): the kebab's transition action must
  // say when transitioning here alone will diverge the booking's group —
  // this is the "approve down the grid" journey the review found gave no
  // warning at all. Unit-tested directly against `groupDivergenceWarning`
  // rather than through a rendered kebab click — see that function's doc
  // comment for why (DataGrid column virtualization never puts the kebab
  // button in the jsdom DOM for this page).
  it('warns naming the group when a booking belongs to one, and says nothing for a hand-picked booking', () => {
    expect(
      groupDivergenceWarning({ environment_group_id: 701, environment_group_name: 'Checkout Squad' })
    ).toBe(
      'In group "Checkout Squad" — transitioning here alone will not move the rest of the group.'
    );

    // Falls back to a numeric label if the name is somehow missing, but
    // still warns — never silently drops the note.
    expect(groupDivergenceWarning({ environment_group_id: 701, environment_group_name: null })).toBe(
      'In group "#701" — transitioning here alone will not move the rest of the group.'
    );

    // Hand-picked (no group): no warning at all.
    expect(
      groupDivergenceWarning({ environment_group_id: null, environment_group_name: null })
    ).toBeNull();
    expect(groupDivergenceWarning(null)).toBeNull();
    expect(groupDivergenceWarning(undefined)).toBeNull();
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

describe('apiAgreementGap', () => {
  it('sends the two real selections as booleans', () => {
    expect(apiAgreementGap('true')).toBe(true);
    expect(apiAgreementGap('false')).toBe(false);
  });

  it('sends nothing at all for no selection', () => {
    // `''` is what the cleared select writes to the URL, and what buildParams
    // already drops. Both routes must end at `undefined`: `?agreement_gap=`
    // is a 422 from FastAPI's Optional[bool], not an ignored param.
    expect(apiAgreementGap(undefined)).toBeUndefined();
    expect(apiAgreementGap('')).toBeUndefined();
  });

  it('sends nothing for a value the server could not parse', () => {
    // Everything read out of the URL is untrusted — a hand-edited or stale
    // link must not 422 the whole grid. `all` is here because it is
    // buildParams' own sentinel and must never mean anything on this filter.
    expect(apiAgreementGap('all')).toBeUndefined();
    expect(apiAgreementGap('any')).toBeUndefined();
    expect(apiAgreementGap('yes')).toBeUndefined();
    expect(apiAgreementGap('1')).toBeUndefined();
  });
});
