import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { customFieldService } from '../services/customFieldService';
import type {
  CustomFieldDefinition,
  CustomFieldDefinitionCreate,
  CustomFieldDefinitionUpdate,
  EntityType,
} from '../types/customField';

interface CustomFieldState {
  definitions: Partial<Record<EntityType, CustomFieldDefinition[]>>;
  loading: boolean;
  error: string | null;
}

const initialState: CustomFieldState = {
  definitions: {},
  loading: false,
  error: null,
};

export const fetchDefinitions = createAsyncThunk(
  'customField/fetchDefinitions',
  (entityType: EntityType) => customFieldService.listDefinitions(entityType)
);

export const createDefinition = createAsyncThunk(
  'customField/createDefinition',
  (data: CustomFieldDefinitionCreate) => customFieldService.createDefinition(data)
);

export const updateDefinition = createAsyncThunk(
  'customField/updateDefinition',
  ({ id, data }: { id: number; data: CustomFieldDefinitionUpdate }) =>
    customFieldService.updateDefinition(id, data)
);

export const deleteDefinition = createAsyncThunk(
  'customField/deleteDefinition',
  async (id: number) => {
    await customFieldService.deleteDefinition(id);
    return id;
  }
);

const customFieldSlice = createSlice({
  name: 'customField',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchDefinitions.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchDefinitions.fulfilled, (state, action) => {
        state.loading = false;
        const entityType = action.meta.arg;
        state.definitions[entityType] = action.payload;
      })
      .addCase(fetchDefinitions.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load fields';
      })
      .addCase(createDefinition.fulfilled, (state, action) => {
        const et = action.payload.entity_type;
        const list = state.definitions[et] ?? [];
        state.definitions[et] = [...list, action.payload].sort(
          (a, b) => a.display_order - b.display_order || a.id - b.id
        );
      })
      .addCase(updateDefinition.fulfilled, (state, action) => {
        const et = action.payload.entity_type;
        state.definitions[et] = (state.definitions[et] ?? []).map((d) =>
          d.id === action.payload.id ? action.payload : d
        );
      })
      .addCase(deleteDefinition.fulfilled, (state, action) => {
        const deletedId = action.payload;
        for (const et of Object.keys(state.definitions) as EntityType[]) {
          state.definitions[et] = (state.definitions[et] ?? []).filter((d) => d.id !== deletedId);
        }
      });
  },
});

export default customFieldSlice.reducer;
