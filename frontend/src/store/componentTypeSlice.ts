import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { ComponentTypeDefinitionResponse } from '../types/componentType';
import { componentTypeService } from '../services/componentTypeService';

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

export const createComponentType = createAsyncThunk(
  'componentType/create',
  (data: Parameters<typeof componentTypeService.createType>[0]) =>
    componentTypeService.createType(data)
);

export const updateComponentType = createAsyncThunk(
  'componentType/update',
  ({ id, data }: { id: number; data: Parameters<typeof componentTypeService.updateType>[1] }) =>
    componentTypeService.updateType(id, data)
);

export const deleteComponentType = createAsyncThunk('componentType/delete', (id: number) =>
  componentTypeService.deleteType(id).then(() => id)
);

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
