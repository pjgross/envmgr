/**
 * Position system-group boxes in three vertical columns: external systems that
 * face the left of the current system stack in a left column, the current
 * system sits in the middle, and right-facing external systems stack in a right
 * column. Stacking same-side systems vertically (rather than in a horizontal
 * row) means several systems linking to the same component fan into it from
 * different heights instead of one system's link crossing another's box.
 */

export interface GroupBox {
  id: number;
  width: number;
  height: number;
}

export interface Origin {
  x: number;
  y: number;
}

export function positionColumns(
  left: GroupBox[],
  current: GroupBox | null,
  right: GroupBox[],
  gap: number
): Map<number, Origin> {
  const columnHeight = (items: GroupBox[]) =>
    items.reduce((sum, b, i) => sum + b.height + (i > 0 ? gap : 0), 0);
  const columnWidth = (items: GroupBox[]) =>
    items.length ? Math.max(...items.map((b) => b.width)) : 0;

  const currentItems = current ? [current] : [];
  const maxHeight = Math.max(
    columnHeight(left),
    columnHeight(currentItems),
    columnHeight(right),
    0
  );

  const leftW = columnWidth(left);
  const curW = current ? current.width : 0;
  const rightW = columnWidth(right);

  const leftX = 0;
  const curX = left.length ? leftW + gap : 0;
  const rightX = curX + curW + (right.length ? gap : 0);

  const origins = new Map<number, Origin>();
  const placeColumn = (items: GroupBox[], colX: number, colW: number) => {
    // Centre the column vertically within the tallest column so fan-in is balanced.
    let y = (maxHeight - columnHeight(items)) / 2;
    for (const b of items) {
      origins.set(b.id, { x: colX + (colW - b.width) / 2, y });
      y += b.height + gap;
    }
  };

  placeColumn(left, leftX, leftW);
  if (current) placeColumn([current], curX, curW);
  placeColumn(right, rightX, rightW);

  return origins;
}
