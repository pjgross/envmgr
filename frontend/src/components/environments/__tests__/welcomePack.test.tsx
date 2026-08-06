/**
 * WelcomePack — dedicated, isolated coverage.
 *
 * These tests render <WelcomePack> on its own (not nested inside
 * EnvironmentRequestDetail), so every assertion is naturally scoped to the
 * pack's own container — there is no sibling "Operations group" field from
 * the request-detail card to collide with, which is exactly what let
 * `screen.getByText('Platform Ops')` in environmentRequestDetail.test.tsx
 * match the wrong node (the detail card, not the pack) and let a
 * member-chip-deleting mutation survive.
 *
 * Fix-pass I3: three mutations previously survived a green suite —
 *   1. deleting the whole "How to connect" section
 *   2. deleting the operating-team name AND every member chip
 *   3. reintroducing the falsy guard the brief forbids (`!== 'Not provided'`)
 * Each test below is written to fail under exactly one of those, not merely
 * under "some" mutation — `getAllByText('Not provided').length > 0` (the
 * only assertion the old suite had) is satisfied by any single survivor.
 */
import { configureStore } from '@reduxjs/toolkit';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import WelcomePack from '../WelcomePack';
import environmentRequestReducer from '../../../store/environmentRequestSlice';
import { environmentRequestService } from '../../../services/environmentRequestService';
import type { WelcomePack as WelcomePackType } from '../../../types/environmentRequest';

vi.mock('../../../services/environmentRequestService', () => ({
  environmentRequestService: {
    getWelcomePack: vi.fn(),
  },
}));

function makePack(overrides: Partial<WelcomePackType> = {}): WelcomePackType {
  return {
    environment: {
      id: 9,
      name: 'Mortgage PERF',
      tier: 'Performance',
      status: 'inactive',
      owner: 'alice',
      expires_at: null,
    },
    access: {
      access_url: 'https://perf.example.com',
      connection_notes: 'VPN then RDP to the app server',
      support_contact: 'ops@example.com',
    },
    support: {
      sla_notes: '9-5 business days',
      operations_group: 'Platform Ops',
      operations_group_members: ['alice', 'bob'],
    },
    caveats: { known_limitations: 'No production data' },
    offboarding: { decommission_notes: 'Snapshot before teardown' },
    context: { requested_by: 'alice', justification: 'Need to verify a fix', kind: 'access' },
    ...overrides,
  };
}

function renderPack(pack: WelcomePackType) {
  vi.mocked(environmentRequestService.getWelcomePack).mockResolvedValue(pack);
  const store = configureStore({ reducer: { environmentRequest: environmentRequestReducer } });
  return render(
    <Provider store={store}>
      <WelcomePack requestId={9} />
    </Provider>
  );
}

describe('WelcomePack', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders every section heading', async () => {
    renderPack(makePack());
    await screen.findByText('Welcome Pack');

    for (const heading of [
      'Environment',
      'How to connect',
      'Support',
      'Known limitations',
      'Offboarding',
      'Context',
    ]) {
      expect(screen.getByText(heading)).toBeInTheDocument();
    }
  });

  // Kills mutation 1 (deleting the whole section) directly — the heading
  // assertion above catches the heading, but a mutation that kept the
  // heading and only dropped the three fields beneath it would survive that
  // alone.
  it("renders the 'How to connect' section's own field values", async () => {
    renderPack(makePack());
    await screen.findByText('Welcome Pack');

    expect(screen.getByText('Access URL: https://perf.example.com')).toBeInTheDocument();
    expect(screen.getByText('VPN then RDP to the app server')).toBeInTheDocument();
    expect(screen.getByText('Support contact: ops@example.com')).toBeInTheDocument();
  });

  // Kills mutation 2: the operating team's name and each member's chip are
  // three separate discriminating assertions, not one combined truthy check.
  it("renders the operating team's name and every member as a chip", async () => {
    renderPack(makePack());
    await screen.findByText('Welcome Pack');

    expect(screen.getByText('Operating team: Platform Ops')).toBeInTheDocument();
    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText('bob')).toBeInTheDocument();
  });

  it('renders "No members" when the operating group has none', async () => {
    renderPack(makePack({ support: {
      sla_notes: 'Not provided', operations_group: 'Not provided', operations_group_members: [],
    } }));
    await screen.findByText('Welcome Pack');

    expect(screen.getByText('No members')).toBeInTheDocument();
  });

  // Kills mutation 3: a reintroduced `!== 'Not provided'` guard hides
  // exactly the node whose value equals that fallback string. Only
  // `connection_notes` is left as a bare, un-prefixed "Not provided" here,
  // so this is a single unambiguous target — a guard anywhere in the
  // component makes it vanish from the DOM rather than merely being one of
  // several redundant matches.
  it('substitutes "Not provided" for an unfilled field rather than hiding it', async () => {
    renderPack(makePack({
      access: {
        access_url: 'Not provided',
        connection_notes: 'Not provided',
        support_contact: 'Not provided',
      },
    }));
    await screen.findByText('Welcome Pack');

    expect(screen.getByText('Access URL: Not provided')).toBeInTheDocument();
    expect(screen.getByText('Not provided')).toBeInTheDocument();
    expect(screen.getByText('Support contact: Not provided')).toBeInTheDocument();
  });

  it("renders the Support/Known limitations/Offboarding/Context sections' own values", async () => {
    renderPack(makePack());
    await screen.findByText('Welcome Pack');

    expect(screen.getByText('SLA: 9-5 business days')).toBeInTheDocument();
    expect(screen.getByText('No production data')).toBeInTheDocument();
    expect(screen.getByText('Snapshot before teardown')).toBeInTheDocument();
    expect(screen.getByText('Requested by: alice')).toBeInTheDocument();
    expect(screen.getByText('Justification: Need to verify a fix')).toBeInTheDocument();
    expect(screen.getByText('Kind: access')).toBeInTheDocument();
  });
});
