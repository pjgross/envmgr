import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'
import { getSystemTopology } from '../services/topologyService'
import type { TopologyResponse } from '../types/topology'

export const fetchTopology = createAsyncThunk(
  'topology/fetch',
  async (systemId: number) => {
    return await getSystemTopology(systemId)
  }
)

interface TopologyState {
  data: TopologyResponse | null
  loading: boolean
  error: string | null
}

const initialState: TopologyState = {
  data: null,
  loading: false,
  error: null,
}

const topologySlice = createSlice({
  name: 'topology',
  initialState,
  reducers: {
    clearTopology: (state) => {
      state.data = null
      state.error = null
      state.loading = false
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchTopology.pending, (state) => {
        state.loading = true
        state.error = null
      })
      .addCase(fetchTopology.fulfilled, (state, action) => {
        state.loading = false
        state.data = action.payload
      })
      .addCase(fetchTopology.rejected, (state, action) => {
        state.loading = false
        state.error = action.error.message ?? 'Failed to load topology'
      })
  },
})

export const { clearTopology } = topologySlice.actions
export default topologySlice.reducer
