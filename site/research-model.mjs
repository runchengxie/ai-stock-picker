export function passRate(passed, total) {
  if (
    !Number.isInteger(passed) ||
    !Number.isInteger(total) ||
    passed < 0 ||
    total < passed
  ) {
    throw new Error("Invalid result count");
  }
  return total === 0 ? null : passed / total;
}

export function returnRows(study, horizon) {
  if (!["H1", "H3", "H5"].includes(horizon))
    throw new Error("Invalid holding period");
  return Object.entries(study.primary).flatMap(([key, periods]) => {
    const value = periods[horizon]?.total_return;
    return typeof value === "number" && Number.isFinite(value)
      ? [{ key, value }]
      : [];
  });
}

export function sortedDays(rows) {
  return [...rows].sort(
    (a, b) =>
      b.date.localeCompare(a.date) ||
      a.arm.localeCompare(b.arm) ||
      a.model.localeCompare(b.model),
  );
}
