import { test } from "node:test";
import assert from "node:assert/strict";
import {
  passRate,
  returnRows,
  sortedDays,
} from "../../site/research-model.mjs";

test("publication rate retains its own denominator", () => {
  assert.equal(passRate(7, 18), 7 / 18);
  assert.equal(passRate(0, 0), null);
  assert.throws(() => passRate(19, 18));
});
test("missing return data is not silently turned into zero", () => {
  assert.deepEqual(returnRows({ primary: {} }, "H1"), []);
  assert.deepEqual(
    returnRows({ primary: { x: { H1: { total_return: null } } } }, "H1"),
    [],
  );
});
test("horizon filtering never mixes holding periods", () => {
  const data = {
    primary: { x: { H1: { total_return: -0.2 }, H3: { total_return: -0.1 } } },
  };
  assert.deepEqual(returnRows(data, "H3"), [{ key: "x", value: -0.1 }]);
  assert.throws(() => returnRows(data, "H2"));
});
test("daily failed states stay in the view and the source is not mutated", () => {
  const rows = [
    { date: "2026-07-20", status: "tombstone", arm: "a", model: "b" },
    { date: "2026-07-21", status: "complete", arm: "a", model: "b" },
  ];
  assert.equal(sortedDays(rows)[1].status, "tombstone");
  assert.equal(rows[0].date, "2026-07-20");
});
