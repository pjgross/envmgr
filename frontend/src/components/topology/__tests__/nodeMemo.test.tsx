import { describe, expect, it } from 'vitest';
import SubsystemNode from '../SubsystemNode';
import SystemGroupNode from '../SystemGroupNode';
import CollapsedSystemNode from '../CollapsedSystemNode';

const MEMO = Symbol.for('react.memo');

describe('node components are memoized', () => {
  it('SubsystemNode is wrapped in React.memo', () => {
    expect((SubsystemNode as any).$$typeof).toBe(MEMO);
  });
  it('SystemGroupNode is wrapped in React.memo', () => {
    expect((SystemGroupNode as any).$$typeof).toBe(MEMO);
  });
  it('CollapsedSystemNode is wrapped in React.memo', () => {
    expect((CollapsedSystemNode as any).$$typeof).toBe(MEMO);
  });
});
