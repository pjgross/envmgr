import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import type { AppDispatch, RootState } from '../store';
import { fetchNamingPolicy } from '../store/environmentNamingPolicySlice';
import type { EnvironmentNamingPolicy } from '../types/environment';

/**
 * The tenant's environment naming policy, for a form's helper text.
 *
 * `GET /tenant/environment-naming-policy` is readable by any tenant member, not
 * just Admins — the reason a name will be refused has to be legible to whoever
 * has to choose one. It answers with a disabled default rather than a 404 when
 * no policy has ever been saved, so there is no not-configured error case.
 *
 * The pattern it returns is for DISPLAY ONLY. Nothing here — and nothing that
 * consumes this — may compile it into a `RegExp`: the verdict is stored on the
 * environment precisely because Python's `re` is the one regex engine in this
 * system, and a browser-side second opinion would disagree with it on real
 * patterns.
 */
export function useNamingPolicy(): { policy: EnvironmentNamingPolicy | null } {
  const dispatch = useDispatch<AppDispatch>();
  const policy = useSelector((s: RootState) => s.environmentNamingPolicy.policy);

  useEffect(() => {
    dispatch(fetchNamingPolicy());
  }, [dispatch]);

  return { policy };
}

/**
 * The helper text for a name field, or undefined when the tenant has no naming
 * rule in force. Undefined rather than an empty string on purpose: a blank
 * helper line under the field implies a rule exists and leaves the reader
 * looking for it.
 */
export function namingPolicyHelperText(
  policy: EnvironmentNamingPolicy | null
): string | undefined {
  if (!policy || !policy.is_enabled || !policy.name_pattern) return undefined;
  const example = policy.name_pattern_example
    ? ` For example: ${policy.name_pattern_example}`
    : '';
  return `The name must match ${policy.name_pattern}.${example}`;
}
