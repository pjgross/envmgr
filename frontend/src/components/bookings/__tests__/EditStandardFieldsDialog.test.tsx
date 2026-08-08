import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import EditStandardFieldsDialog from '../EditStandardFieldsDialog';
import type { BookingResponse } from '../../../types/booking';
import type { ProjectResponse } from '../../../types/project';

// The Project picker's source — useAllProjects, which calls
// projectService.listProjects({ is_active: true, limit: 500 }). No HTTP:
// these tests are about the dialog's wiring, not what the server returns.
vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi.fn(),
  },
}));

import { projectService } from '../../../services/projectService';

// Fixture ids/names chosen to appear in no other mock in this file — on A2,
// three tests passed via the wrong data source because a fixture id
// coincided with another mock's.
const HARBOR: ProjectResponse = {
  id: 741,
  tenant_id: 1,
  name: 'Harborlight Migration',
  code: 'HRB',
  description: null,
  team_group_id: null,
  team_group_name: null,
  environment_count: 0,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const BOOKING: BookingResponse = {
  id: 1,
  environment_id: 1,
  environment_name: 'Env A',
  project_name: 'Regression sweep',
  project_id: null,
  project_name_link: null,
  booked_by: 1,
  booked_by_username: 'alice',
  start_date: '2026-08-10T09:00:00Z',
  end_date: '2026-08-11T09:00:00Z',
  booking_type_id: 5,
  exclusive_use: false,
  status: 'draft',
  notes: null,
  recurrence_rule: null,
  recurrence_parent_id: null,
  release_id: null,
  test_phase_id: null,
  context_tag: 'none',
  custom_fields: null,
  environment_group_id: null,
  environment_group_name: null,
  standard_field_permissions: {
    project_name: { editable: true },
    start_date: { editable: true },
    end_date: { editable: true },
    booking_type: { editable: true },
    notes: { editable: true },
    exclusive_use: { editable: true },
    context_tag: { editable: true },
    // Deliberately no "project_id" entry — ENTITY_FIELD_SPECS never emits
    // one for this field (see EditStandardFieldsDialog's canEdit comment).
    // Omitting it here rather than adding a fabricated permission proves
    // the dialog does not depend on one being present.
  },
  tenant_id: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

// A booking already linked to a project that has since been archived (id
// 852, distinct from HARBOR and from any other fixture in this file) — it
// is deliberately NOT among the rows useAllProjects({ is_active: true })
// resolves, so it only appears via the carve-out.
const ARCHIVED_BOOKING: BookingResponse = {
  ...BOOKING,
  project_id: 852,
  project_name_link: 'Wound Down Programme',
};

describe('EditStandardFieldsDialog', () => {
  beforeEach(() => {
    vi.mocked(projectService.listProjects).mockReset().mockResolvedValue({
      rows: [HARBOR],
      total: 1,
    });
  });

  // This is the booking's own edit path for the free-text project_name
  // field — Task 7 relabelled it "Purpose" everywhere else but missed this
  // dialog, so a user editing a booking's Purpose here still saw "Project
  // Name", one dialog away from the new, unrelated Project picker.
  it('labels the free-text field "Purpose", not "Project Name"', () => {
    render(
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={vi.fn()}
      />
    );

    expect(screen.getByLabelText('Purpose')).toBeInTheDocument();
    expect(screen.queryByLabelText('Project Name')).not.toBeInTheDocument();
  });

  it('sources the Project picker from active projects only', async () => {
    render(
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={vi.fn()}
      />
    );

    await waitFor(() =>
      expect(projectService.listProjects).toHaveBeenCalledWith(
        expect.objectContaining({ is_active: true })
      )
    );
  });

  it('renders a Project field and sends project_id on save', async () => {
    const user = userEvent.setup();
    const saver = vi.fn().mockResolvedValue({ ...BOOKING, project_id: HARBOR.id });
    const onSaved = vi.fn();

    render(
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={onSaved}
        saver={saver}
      />
    );

    await user.click(screen.getByRole('combobox', { name: 'Project' }));
    await user.click(await screen.findByRole('option', { name: 'Harborlight Migration' }));

    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(saver).toHaveBeenCalledTimes(1));
    expect(saver.mock.calls[0][0]).toMatchObject({ project_id: HARBOR.id });
  });

  it('offers "None" and sends null when no project is chosen (the link is optional)', async () => {
    const user = userEvent.setup();
    const saver = vi.fn().mockResolvedValue(BOOKING);

    render(
      <EditStandardFieldsDialog
        open
        booking={{ ...BOOKING, project_id: HARBOR.id, project_name_link: HARBOR.name }}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={saver}
      />
    );

    await waitFor(() => expect(screen.getByText('Harborlight Migration')).toBeInTheDocument());

    await user.click(screen.getByRole('combobox', { name: 'Project' }));
    await user.click(await screen.findByRole('option', { name: 'None' }));

    await user.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(saver).toHaveBeenCalledTimes(1));
    expect(saver.mock.calls[0][0]).toMatchObject({ project_id: null });
  });

  it('carves out the stored value when the booking\'s project has been archived', async () => {
    const saver = vi.fn().mockResolvedValue(ARCHIVED_BOOKING);

    render(
      <EditStandardFieldsDialog
        open
        booking={ARCHIVED_BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={saver}
      />
    );

    // The archived project (852) is not in useAllProjects' active list —
    // only HARBOR is — yet it must still render by name so the form does
    // not silently clear a link the backend deliberately preserves.
    await waitFor(() =>
      expect(screen.getByText(/wound down programme/i)).toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(saver).toHaveBeenCalledTimes(1));
    expect(saver.mock.calls[0][0]).toMatchObject({ project_id: 852 });
  });

  it('shows a truncation notice when the server holds more active projects than were fetched', async () => {
    vi.mocked(projectService.listProjects).mockResolvedValue({ rows: [HARBOR], total: 2 });

    render(
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={vi.fn()}
      />
    );

    expect(await screen.findByText(/only the first 1 projects are shown/i)).toBeInTheDocument();
  });

  // Re-render, not only mount: in the real app the dialog is not
  // conditionally mounted on `open` (BookingDetail keeps it in the tree and
  // toggles the prop; MUI's Dialog only hides its content), so
  // useAllProjects' effect runs once on mount and must survive the dialog
  // being closed and reopened without losing what it already fetched or
  // re-fetching needlessly. Two A2 defects were stale state that only a
  // second render surfaced.
  it('keeps the fetched Project options across a close/reopen re-render', async () => {
    const { rerender } = render(
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={vi.fn()}
      />
    );

    await waitFor(() => expect(projectService.listProjects).toHaveBeenCalledTimes(1));

    rerender(
      <EditStandardFieldsDialog
        open={false}
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={vi.fn()}
      />
    );

    rerender(
      <EditStandardFieldsDialog
        open
        booking={BOOKING}
        bookingTypes={[]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
        saver={vi.fn()}
      />
    );

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    expect(await screen.findByRole('option', { name: 'Harborlight Migration' })).toBeInTheDocument();
    // Fetched exactly once across mount + two re-renders — the effect's
    // dependency is the constant useSharedList key, not `open`.
    expect(projectService.listProjects).toHaveBeenCalledTimes(1);
  });
});
