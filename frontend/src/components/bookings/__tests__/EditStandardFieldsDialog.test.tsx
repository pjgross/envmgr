import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EditStandardFieldsDialog from '../EditStandardFieldsDialog';
import type { BookingResponse } from '../../../types/booking';

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
  standard_field_permissions: {
    project_name: { editable: true },
    start_date: { editable: true },
    end_date: { editable: true },
    booking_type: { editable: true },
    notes: { editable: true },
    exclusive_use: { editable: true },
    context_tag: { editable: true },
  },
  tenant_id: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('EditStandardFieldsDialog', () => {
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
});
