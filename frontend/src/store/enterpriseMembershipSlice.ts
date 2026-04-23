import { createSlice, createAsyncThunk } from "@reduxjs/toolkit";
import type { ReleaseMembership } from "../types/enterpriseMembership";
import { enterpriseMembershipService } from "../services/enterpriseMembershipService";

interface State {
  byEnterprise: Record<number, ReleaseMembership[]>;
  loading: boolean;
  error?: string;
}

const initialState: State = { byEnterprise: {}, loading: false };

export const fetchMemberships = createAsyncThunk(
  "enterpriseMembership/fetch",
  async (args: { enterpriseId: number; states?: string[] }) => {
    const rows = await enterpriseMembershipService.list(args.enterpriseId, args.states);
    return { enterpriseId: args.enterpriseId, rows };
  }
);

export const requestMembership = createAsyncThunk(
  "enterpriseMembership/request",
  async (args: { enterpriseId: number; projectReleaseId: number; notes?: string }) => {
    const m = await enterpriseMembershipService.request(
      args.enterpriseId,
      { project_release_id: args.projectReleaseId, notes: args.notes }
    );
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const acceptMembership = createAsyncThunk(
  "enterpriseMembership/accept",
  async (args: { enterpriseId: number; membershipId: number }) => {
    const m = await enterpriseMembershipService.accept(args.enterpriseId, args.membershipId);
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const rejectMembership = createAsyncThunk(
  "enterpriseMembership/reject",
  async (args: { enterpriseId: number; membershipId: number; notes: string }) => {
    const m = await enterpriseMembershipService.reject(args.enterpriseId, args.membershipId, { notes: args.notes });
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const withdrawMembership = createAsyncThunk(
  "enterpriseMembership/withdraw",
  async (args: { enterpriseId: number; membershipId: number }) => {
    const m = await enterpriseMembershipService.withdraw(args.enterpriseId, args.membershipId);
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

export const removeMembership = createAsyncThunk(
  "enterpriseMembership/remove",
  async (args: { enterpriseId: number; membershipId: number; reason: string }) => {
    const m = await enterpriseMembershipService.remove(args.enterpriseId, args.membershipId, { reason: args.reason });
    return { enterpriseId: args.enterpriseId, membership: m };
  }
);

const upsert = (state: State, action: { payload: { enterpriseId: number; membership: ReleaseMembership } }) => {
  const { enterpriseId, membership } = action.payload;
  const list = state.byEnterprise[enterpriseId] ?? [];
  const idx = list.findIndex((m) => m.id === membership.id);
  if (idx >= 0) list[idx] = membership; else list.unshift(membership);
  state.byEnterprise[enterpriseId] = list;
};

const slice = createSlice({
  name: "enterpriseMembership",
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchMemberships.pending, (s) => { s.loading = true; });
    b.addCase(fetchMemberships.fulfilled, (s, a) => {
      s.loading = false;
      s.byEnterprise[a.payload.enterpriseId] = a.payload.rows;
    });
    b.addCase(fetchMemberships.rejected, (s, a) => {
      s.loading = false; s.error = a.error.message;
    });
    b.addCase(requestMembership.fulfilled, upsert);
    b.addCase(acceptMembership.fulfilled, upsert);
    b.addCase(rejectMembership.fulfilled, upsert);
    b.addCase(withdrawMembership.fulfilled, upsert);
    b.addCase(removeMembership.fulfilled, upsert);
  },
});

export default slice.reducer;
