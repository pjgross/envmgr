import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit'
import { bookingRequestService } from '../services/bookingRequestService'
import type {
  BookingRequestResponse,
  BookingRequestCreatePayload,
  BookingRequestCreateResponse,
} from '../types/bookingRequest'

type State = {
  requests: BookingRequestResponse[]
  loading: boolean
  error: string | null
}

const initialState: State = { requests: [], loading: false, error: null }

export const fetchBookingRequests = createAsyncThunk(
  'bookingRequest/list',
  async () => await bookingRequestService.list(),
)

export const fetchBookingRequest = createAsyncThunk(
  'bookingRequest/get',
  async (id: number) => await bookingRequestService.get(id),
)

export const createBookingRequest = createAsyncThunk(
  'bookingRequest/create',
  async (payload: BookingRequestCreatePayload) => await bookingRequestService.create(payload),
)

export const addEnvironmentToRequest = createAsyncThunk(
  'bookingRequest/addEnv',
  async (args: { id: number; environment_id: number; start_date?: string; end_date?: string }) =>
    await bookingRequestService.addEnvironment(args.id, {
      environment_id: args.environment_id,
      start_date: args.start_date,
      end_date: args.end_date,
    }),
)

export const removeEnvironmentFromRequest = createAsyncThunk(
  'bookingRequest/removeEnv',
  async (args: { id: number; bookingId: number }) => {
    await bookingRequestService.removeEnvironment(args.id, args.bookingId)
    return args
  },
)

export const updateRequestStandardFields = createAsyncThunk(
  'bookingRequest/updateStandard',
  async (args: { id: number; values: Record<string, unknown> }) =>
    await bookingRequestService.updateStandardFields(args.id, args.values),
)

export const updateRequestCustomFields = createAsyncThunk(
  'bookingRequest/updateCustom',
  async (args: { id: number; values: Record<string, unknown> }) =>
    await bookingRequestService.updateCustomFields(args.id, args.values),
)

const slice = createSlice({
  name: 'bookingRequest',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchBookingRequests.pending, (s) => { s.loading = true; s.error = null })
    b.addCase(fetchBookingRequests.fulfilled, (s, a: PayloadAction<BookingRequestResponse[]>) => {
      s.loading = false; s.requests = a.payload
    })
    b.addCase(fetchBookingRequests.rejected, (s, a) => {
      s.loading = false; s.error = a.error.message ?? 'Failed to load'
    })
    b.addCase(createBookingRequest.fulfilled, (s, a: PayloadAction<BookingRequestCreateResponse>) => {
      s.requests.unshift(a.payload.request)
    })
    b.addCase(fetchBookingRequest.fulfilled, (s, a: PayloadAction<BookingRequestResponse>) => {
      const i = s.requests.findIndex((r) => r.id === a.payload.id)
      if (i === -1) s.requests.push(a.payload)
      else s.requests[i] = a.payload
    })
    b.addCase(updateRequestStandardFields.fulfilled, (s, a: PayloadAction<BookingRequestResponse>) => {
      const i = s.requests.findIndex((r) => r.id === a.payload.id)
      if (i !== -1) s.requests[i] = a.payload
    })
    b.addCase(updateRequestCustomFields.fulfilled, (s, a: PayloadAction<BookingRequestResponse>) => {
      const i = s.requests.findIndex((r) => r.id === a.payload.id)
      if (i !== -1) s.requests[i] = a.payload
    })
  },
})

export default slice.reducer
