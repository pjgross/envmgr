import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { ComponentTypeDefinitionResponse } from '../types/componentType';
import { componentTypeService } from '../services/componentTypeService';
import { formatApiError } from '../services/apiError';

interface ComponentTypeState {
  definitions: ComponentTypeDefinitionResponse[];
  loading: boolean;
  error: string | null;
}

const initialState: ComponentTypeState = {
  definitions: [],
  loading: false,
  error: null,
};

export const fetchComponentTypes = createAsyncThunk('componentType/fetchAll', () =>
  componentTypeService.listTypes()
);

// The mutating thunks reject with `rejectWithValue(formatApiError(...))` rather
// than letting the axios error escape. Redux Toolkit serialises an escaping
// error with `miniSerializeError`, which copies only name/message/stack/code —
// `response.data.detail`, where the backend puts its actual explanation, is
// dropped, and a real AxiosError's `.message` is the generic "Request failed
// with status code 409". Consumers must therefore read `result.payload`, not
// `result.error.message`.
export const createComponentType = createAsyncThunk<
  ComponentTypeDefinitionResponse,
  Parameters<typeof componentTypeService.createType>[0],
  { rejectValue: string }
>('componentType/create', async (data, { rejectWithValue }) => {
  try {
    return await componentTypeService.createType(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create component type'));
  }
});

export const updateComponentType = createAsyncThunk<
  ComponentTypeDefinitionResponse,
  { id: number; data: Parameters<typeof componentTypeService.updateType>[1] },
  { rejectValue: string }
>('componentType/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await componentTypeService.updateType(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update component type'));
  }
});

export const deleteComponentType = createAsyncThunk<
  number,
  number,
  { rejectValue: string }
>('componentType/delete', async (id, { rejectWithValue }) => {
  try {
    await componentTypeService.deleteType(id);
    return id;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to delete component type'));
  }
});

const componentTypeSlice = createSlice({
  name: 'componentType',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchComponentTypes.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchComponentTypes.fulfilled, (state, action) => {
        state.loading = false;
        state.definitions = action.payload;
      })
      .addCase(fetchComponentTypes.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch component types';
      })
      .addCase(createComponentType.fulfilled, (state, action) => {
        state.definitions.push(action.payload);
      })
      .addCase(updateComponentType.fulfilled, (state, action) => {
        const idx = state.definitions.findIndex((d) => d.id === action.payload.id);
        if (idx !== -1) state.definitions[idx] = action.payload;
      })
      .addCase(deleteComponentType.fulfilled, (state, action) => {
        state.definitions = state.definitions.filter((d) => d.id !== action.payload);
      });
  },
});

export default componentTypeSlice.reducer;
