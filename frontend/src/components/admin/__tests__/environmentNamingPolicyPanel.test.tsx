import { configureStore } from '@reduxjs/toolkit';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import EnvironmentNamingPolicyPanel from '../EnvironmentNamingPolicyPanel';
import environmentNamingPolicyReducer from '../../../store/environmentNamingPolicySlice';
import customFieldReducer from '../../../store/customFieldSlice';
import { environmentNamingPolicyService } from '../../../services/environmentNamingPolicyService';
import { customFieldService } from '../../../services/customFieldService';

vi.mock('../../../services/environmentNamingPolicyService', () => ({
  environmentNamingPolicyService: {
    get: vi.fn(),
    save: vi.fn(),
    preview: vi.fn(),
  },
}));

// The attribute picker's `cf:<field_key>` options come from the environment
// custom-field definitions, so this service is a real dependency of the panel.
// Left unmocked it would reach for axios in jsdom.
vi.mock('../../../services/customFieldService', () => ({
  customFieldService: {
    listDefinitions: vi.fn(),
    createDefinition: vi.fn(),
    updateDefinition: vi.fn(),
    deleteDefinition: vi.fn(),
  },
}));

const POLICY = {
  is_enabled: true,
  name_pattern: '[a-z]+-(dev|uat|prod)-\\d{2}',
  name_pattern_example: 'payments-uat-01',
  required_attributes: ['owner'],
  grace_days: 14,
  effective_from: '2026-08-09T00:00:00Z',
};

const COST_CENTRE_FIELD = {
  id: 7,
  tenant_id: 1,
  entity_type: 'environment' as const,
  entity_subtype: null,
  field_key: 'cost_centre',
  label: 'Cost centre',
  field_type: 'text' as const,
  required: false,
  display_order: 10,
  options: null,
  lifecycle_states: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

function renderPanel() {
  const store = configureStore({
    reducer: {
      environmentNamingPolicy: environmentNamingPolicyReducer,
      customField: customFieldReducer,
    },
  });
  return render(
    <Provider store={store}>
      <EnvironmentNamingPolicyPanel />
    </Provider>
  );
}

beforeEach(() => {
  vi.mocked(environmentNamingPolicyService.get).mockResolvedValue(POLICY);
  vi.mocked(environmentNamingPolicyService.save).mockResolvedValue(POLICY);
  vi.mocked(environmentNamingPolicyService.preview).mockResolvedValue({
    total_environments: 12,
    in_gap: 9,
    quarantined_now: 0,
    sample_names: ['Legacy Box'],
  });
  vi.mocked(customFieldService.listDefinitions).mockResolvedValue([COST_CENTRE_FIELD]);
});

describe('EnvironmentNamingPolicyPanel', () => {
  it('loads the policy in force', async () => {
    renderPanel();
    expect(await screen.findByDisplayValue('payments-uat-01')).toBeInTheDocument();
    expect(screen.getByDisplayValue('[a-z]+-(dev|uat|prod)-\\d{2}')).toBeInTheDocument();
  });

  it('previews who a rule would hit before it is saved', async () => {
    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /preview/i }));
    expect(await screen.findByText(/9 of 12/i)).toBeInTheDocument();
    expect(screen.getByText(/none quarantined/i)).toBeInTheDocument();
  });

  it('previews the pattern in the form, not the one last saved', async () => {
    // The whole point of a preview is to answer "what would this do" before it
    // is in force. Sending the saved policy would answer a question nobody
    // asked and report a reassuring number for a rule about to change.
    renderPanel();
    const pattern = await screen.findByDisplayValue('[a-z]+-(dev|uat|prod)-\\d{2}');
    await userEvent.clear(pattern);
    // paste, not type: userEvent.type reads `[...]` as key descriptors and
    // throws on a character class, which every real pattern contains.
    await userEvent.click(pattern);
    await userEvent.paste('env-[0-9]+');
    await userEvent.click(screen.getByRole('button', { name: /preview/i }));

    await waitFor(() =>
      expect(environmentNamingPolicyService.preview).toHaveBeenCalledWith({
        name_pattern: 'env-[0-9]+',
        required_attributes: ['owner'],
      })
    );
  });

  it('saves only the keys PUT accepts — never effective_from', async () => {
    // EnvironmentNamingPolicyUpdate declares extra='forbid' and has no
    // effective_from (the server owns that date), so echoing the read model
    // back is a 422 on EVERY save —
    // test_an_unknown_key_is_refused_not_silently_dropped pins the server half.
    // The type system makes this hard to get wrong; it does not make it
    // impossible, and a mocked service cannot notice.
    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(environmentNamingPolicyService.save).toHaveBeenCalled());
    const body = vi.mocked(environmentNamingPolicyService.save).mock.calls[0][0];
    expect(Object.keys(body).sort()).toEqual([
      'grace_days',
      'is_enabled',
      'name_pattern',
      'name_pattern_example',
      'required_attributes',
    ]);
  });

  it('sends a blank pattern as null, meaning "attributes only"', async () => {
    // '' is not a pattern that matches nothing — the column is nullable and
    // null is what the backend reads as "no naming rule in force".
    renderPanel();
    const pattern = await screen.findByDisplayValue('[a-z]+-(dev|uat|prod)-\\d{2}');
    await userEvent.clear(pattern);
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(environmentNamingPolicyService.save).toHaveBeenCalledWith(
        expect.objectContaining({ name_pattern: null })
      )
    );
  });

  it('shows the server error text, not an HTTP status', async () => {
    // RTK's default serializer copies only name/message/stack/code, so a real
    // AxiosError's .message is "Request failed with status code 422" and the
    // server's response.data.detail is dropped. Mocking a plain Error carrying
    // the final text would pass while the app is broken — so mock the Axios
    // shape.
    const axiosError = Object.assign(new Error('Request failed with status code 422'), {
      isAxiosError: true,
      response: { status: 422, data: { detail: 'That pattern is too slow to evaluate safely' } },
    });
    vi.mocked(environmentNamingPolicyService.save).mockRejectedValue(axiosError);

    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByText(/too slow to evaluate safely/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/status code 422/i)).not.toBeInTheDocument();
  });

  it('never evaluates the tenant pattern in the browser', async () => {
    // A JS regex engine would be a fourth opinion on a rule this design gives
    // one owner (Python's `re`, in environment_compliance_service.name_matches).
    // Asserting RegExp.prototype.test was never called AT ALL would fail on
    // MUI's and emotion's own internal regexes, so record the sources and
    // assert the tenant's pattern is not among them — which is the actual rule.
    const sources: string[] = [];
    const realTest = RegExp.prototype.test;
    const spy = vi
      .spyOn(RegExp.prototype, 'test')
      .mockImplementation(function (this: RegExp, s: string) {
        sources.push(this.source);
        return realTest.call(this, s);
      });

    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /preview/i }));
    await screen.findByText(/9 of 12/i);

    expect(environmentNamingPolicyService.preview).toHaveBeenCalled();
    expect(sources).not.toContain(POLICY.name_pattern);
    spy.mockRestore();
  });

  it('distinguishes a custom field whose label collides with a fixed attribute', async () => {
    // Found by opening the page. The dev tenant has a custom field keyed
    // `owner` and LABELLED "Owner", so the picker showed two options both
    // reading "Owner" — indistinguishable in the list, identical as chips once
    // selected. The jsdom fixture used "Cost centre", which could not collide,
    // so no test could have caught it. Same collision class the grid columns
    // solved by namespacing `cf_`, in a picker rather than a column id.
    vi.mocked(customFieldService.listDefinitions).mockResolvedValue([
      { ...COST_CENTRE_FIELD, field_key: 'owner', label: 'Owner' },
    ]);
    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('combobox', { name: /required attributes/i }));

    const owners = await screen.findAllByRole('option', { name: /owner/i });
    expect(owners).toHaveLength(2);
    expect(new Set(owners.map((o) => o.textContent))).toHaveLength(2);
    expect(screen.getByRole('option', { name: 'Owner (custom field)' })).toBeInTheDocument();
  });

  it('claims no effective date for a policy that is not in force', async () => {
    // The endpoint answers a never-saved policy with a DISABLED DEFAULT whose
    // effective_from is now, rather than 404ing — so an ungated caption
    // announced "In force since <today>" on a tenant that had never saved one.
    vi.mocked(environmentNamingPolicyService.get).mockResolvedValue({
      ...POLICY,
      is_enabled: false,
    });
    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    expect(screen.queryByText(/in force since/i)).not.toBeInTheDocument();
  });

  it('offers each environment custom field as a requirable attribute', async () => {
    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('combobox', { name: /required attributes/i }));

    expect(await screen.findByRole('option', { name: /cost centre/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /owner/i })).toBeInTheDocument();
    // 'tier' is deliberately absent from the vocabulary: environment.tier_id is
    // already nullable=False, so requiring it is a check that can never fail.
    expect(screen.queryByRole('option', { name: /^tier$/i })).not.toBeInTheDocument();
  });

  it('says that listing an attribute reports rather than refuses', async () => {
    renderPanel();
    await screen.findByDisplayValue('payments-uat-01');
    expect(screen.getByText(/affects reporting only/i)).toBeInTheDocument();
    expect(screen.getByText(/never frozen/i)).toBeInTheDocument();
  });
});
