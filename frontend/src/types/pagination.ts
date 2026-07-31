/**
 * A windowed list response. Endpoints return a bare JSON array with the
 * unwindowed total in `X-Total-Count`, so the total has to be lifted out of the
 * headers before the rows reach Redux.
 */
export interface Paged<T> {
  rows: T[];
  total: number;
}
