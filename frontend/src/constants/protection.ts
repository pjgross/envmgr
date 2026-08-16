/**
 * How hard a booking's claim on an environment is (Phase 7 B4).
 *
 * NOT the same axis as `exclusive_use_requested`. Exclusive use asks "can
 * anyone else be in here with me"; this asks "can I be pushed out".
 *
 * B4 ADVISES: nothing in the UI may disable a control, hide an action or
 * refuse a submit on the strength of this value. It is rendered, it is
 * filtered on, and it appears in A4's verdict. That is all.
 */
export const PROTECTION_LEVELS = ['soft', 'hard'] as const;
export type ProtectionLevel = (typeof PROTECTION_LEVELS)[number];

export const PROTECTION_LABELS: Record<ProtectionLevel, string> = {
  soft: 'Preemptible',
  hard: 'Protected',
};

/**
 * The words that mark a hard reservation on the surfaces that have no room for
 * a chip — the booking calendar and the schedule Gantt. Colour alone cannot
 * carry it: both already spend colour on the booking's STATUS, and an outline
 * difference reaches neither a screen reader nor anyone who cannot tell two
 * hues apart. Lives here rather than in either component so the two cannot
 * drift into saying different things about one fact.
 */
export const PROTECTED_MARKER = 'Protected (hard) reservation';

/**
 * The URL's spelling of "no protection filter". `any`, NEVER `all` — `all` is
 * `buildParams`' own no-selection sentinel, so a vocabulary containing it
 * builds byte-identical params for two different states and the grid never
 * refetches. Third sub-project to hit this (A3, A4, B2).
 */
export const PROTECTION_FILTER_NONE = 'any';
