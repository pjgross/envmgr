import { describe, expect, it } from 'vitest';
import SubsystemNode from '../SubsystemNode';
import SystemGroupNode from '../SystemGroupNode';
import CollapsedSystemNode from '../CollapsedSystemNode';

const MEMO = Symbol.for('react.memo');

/** React tags memoized components with a $$typeof symbol not present on the
 *  public component type. */
const typeTag = (component: unknown) =>
  (component as { $$typeof?: symbol }).$$typeof;

describe('node components are memoized', () => {
  it('SubsystemNode is wrapped in React.memo', () => {
    expect(typeTag(SubsystemNode)).toBe(MEMO);
  });
  it('SystemGroupNode is wrapped in React.memo', () => {
    expect(typeTag(SystemGroupNode)).toBe(MEMO);
  });
  it('CollapsedSystemNode is wrapped in React.memo', () => {
    expect(typeTag(CollapsedSystemNode)).toBe(MEMO);
  });
});
