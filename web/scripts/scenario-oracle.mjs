/** Test-only oracle for Backend scenarios-v5/v6.
 *
 * It deliberately receives the same four fields as the active public API:
 * id, skill, title and options. Values are parsed from the displayed title;
 * no private parameters, answer, seed or saved server snapshot are read.
 * This module is not imported by the application bundle.
 */

function capture(title, pattern, label) {
  const match = title.match(pattern);
  if (!match) throw new Error(`Cannot parse ${label} from public title`);
  return match;
}

function jsonCapture(title, pattern, label, group = 1) {
  const raw = capture(title, pattern, label)[group];
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`Invalid displayed JSON for ${label}`);
  }
}

function pythonRecords(title) {
  const records = [
    ...title.matchAll(
      /\{'id':\s*(\d+),\s*'active':\s*(True|False),\s*'value':\s*(\d+)\}/g,
    ),
  ].map((match) => ({
    id: Number(match[1]),
    active: match[2] === "True",
    value: Number(match[3]),
  }));
  if (!records.length)
    throw new Error("Cannot parse Python records from public title");
  return records;
}

function pythonAnswer(title) {
  if (title.includes("result = [r['id'] for r in records if")) {
    const records = pythonRecords(title);
    const minimum = title.match(/r\['value'\]\s*>=\s*(\d+)/)?.[1];
    return records
      .filter(
        (row) =>
          row.active && (minimum === undefined || row.value >= Number(minimum)),
      )
      .map((row) => row.id);
  }
  if (title.startsWith("def remember(value, bucket=[]):")) {
    const first = Number(
      capture(title, /first = remember\((\d+)\)/, "first call")[1],
    );
    const second = capture(
      title,
      /second = remember\((\d+)(, \[\])?\)/,
      "second call",
    );
    return second[2] ? [Number(second[1])] : [first, Number(second[1])];
  }
  if (title.includes("state = {'queue':") && title.includes("backup = ")) {
    const original = Number(
      capture(title, /'queue': \[(\d+)\]/, "original queue")[1],
    );
    const appended = Number(
      capture(title, /queue'\]\.append\((\d+)\)/, "appended value")[1],
    );
    return title.includes("copy.deepcopy(state)")
      ? [original]
      : [original, appended];
  }
  if (
    title.includes("failed = []") &&
    title.includes("except (ZeroDivisionError, ValueError):")
  ) {
    const records = pythonRecords(title);
    const limit = title.match(/row\['value'\]\s*>\s*(\d+)/)?.[1];
    return records
      .filter(
        (row) =>
          row.value === 0 || (limit !== undefined && row.value > Number(limit)),
      )
      .map((row) => row.id);
  }
  return undefined;
}

function sqlAnswer(title) {
  if (title.startsWith("SQLite. users(id INTEGER, email TEXT) = ")) {
    const users = jsonCapture(
      title,
      /^SQLite\. users\(id INTEGER, email TEXT\) = (\[.*\])\.\nSELECT/m,
      "users",
    );
    const includeEmpty = title.includes("OR email = ''");
    return users
      .filter(
        (user) => user.email === null || (includeEmpty && user.email === ""),
      )
      .map((user) => user.id)
      .sort((a, b) => a - b);
  }
  if (title.startsWith("SQLite. orders(id, user_id, amount, status) = ")) {
    const orders = jsonCapture(
      title,
      /^SQLite\. orders\(id, user_id, amount, status\) = (\[.*\])\.\nSELECT/m,
      "orders",
    );
    const paidOnly = title.includes(" WHERE status = 'paid'");
    const minimum = Number(
      capture(title, /HAVING SUM\(amount\) >= (\d+)/, "HAVING limit")[1],
    );
    const sums = new Map();
    for (const order of orders) {
      if (paidOnly && order.status !== "paid") continue;
      sums.set(order.user_id, (sums.get(order.user_id) || 0) + order.amount);
    }
    return [...sums]
      .filter(([, sum]) => sum >= minimum)
      .sort(([left], [right]) => left - right);
  }
  if (
    title.startsWith("SQLite. users = ") &&
    title.includes(" LEFT JOIN orders ")
  ) {
    const match = capture(
      title,
      /^SQLite\. users = (\[.*\]); orders = (\[.*\])\.\nSELECT/m,
      "LEFT JOIN data",
    );
    const users = JSON.parse(match[1]);
    const orders = JSON.parse(match[2]);
    const paidOnly = title.includes("AND o.status='paid'");
    return [...users]
      .sort((left, right) => left.id - right.id)
      .map((user) => [
        user.id,
        orders.filter(
          (order) =>
            order.user_id === user.id && (!paidOnly || order.status === "paid"),
        ).length,
      ]);
  }
  if (
    title.startsWith("SQLite. orders = ") &&
    title.includes(" ORDER BY amount DESC, id ASC LIMIT ")
  ) {
    const orders = jsonCapture(
      title,
      /^SQLite\. orders = (\[.*\])\.\nSELECT/m,
      "ordered rows",
    );
    const paidOnly = title.includes(" WHERE status='paid'");
    const limit = Number(capture(title, / LIMIT (\d+)/, "LIMIT")[1]);
    return orders
      .filter((order) => !paidOnly || order.status === "paid")
      .sort((left, right) => right.amount - left.amount || left.id - right.id)
      .slice(0, limit)
      .map((order) => order.id);
  }
  return undefined;
}

function httpAnswer(title) {
  if (title.startsWith("POST /offers.")) {
    const events = jsonCapture(
      title,
      /Последовательные запросы: (\[.*\])\. Какие номера/,
      "requests",
    );
    const bodies = new Map();
    const result = [];
    const conflicts = title.includes("получат 409");
    events.forEach((event, index) => {
      if (!bodies.has(event.key)) bodies.set(event.key, event.body);
      else if (!conflicts || bodies.get(event.key) !== event.body)
        result.push(index + 1);
    });
    return result;
  }
  if (title.startsWith("Изначально контакты скрыты всем.")) {
    const events = jsonCapture(
      title,
      /События: (\[.*\])\. Какие компании/,
      "contact events",
    );
    const grants = new Set();
    for (const event of events) {
      if (event.action === "accept") grants.add(event.company);
      else if (event.action === "revoke") grants.delete(event.company);
    }
    return [...grants].sort();
  }
  if (title.startsWith('Ресурс имеет ETag "')) {
    let current = Number(capture(title, /ETag "(\d+)"/, "initial ETag")[1]);
    const conditions = jsonCapture(
      title,
      /Последовательные If-Match: (\[.*\])\./,
      "If-Match sequence",
    );
    const result = [];
    conditions.forEach((condition, index) => {
      if (condition === current) {
        result.push(index + 1);
        current += 1;
      }
    });
    return result;
  }
  if (title.includes("GET /company/offers/")) {
    const session = capture(
      title,
      /Сессия: role=(employer|candidate), company=«([^»]+)»/,
      "session",
    );
    const role = session[1];
    const actor = session[2];
    const two = title.match(
      /GET \/company\/offers\/(\d+) и GET \/company\/offers\/(\d+)\. Приглашение \d+ принадлежит компании «([^»]+)», приглашение \d+ — компании «([^»]+)»/,
    );
    if (two) {
      const offers = [
        [Number(two[1]), two[3]],
        [Number(two[2]), two[4]],
      ];
      return offers
        .filter(([, owner]) => role === "employer" && owner === actor)
        .map(([offerId]) => offerId);
    }
    const one = capture(
      title,
      /GET \/company\/offers\/(\d+)\. Приглашение принадлежит компании «([^»]+)»/,
      "owned offer",
    );
    return role === "employer" && actor === one[2] ? [Number(one[1])] : [];
  }
  return undefined;
}

function sameJson(left, right) {
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJson(value, right[index]))
    );
  }
  if (left && right && typeof left === "object" && typeof right === "object") {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return (
      sameJson(leftKeys, rightKeys) &&
      leftKeys.every((key) => sameJson(left[key], right[key]))
    );
  }
  return Object.is(left, right);
}

export function scenarioAnswer(question, grade = "junior") {
  if (
    !question ||
    typeof question.id !== "string" ||
    typeof question.title !== "string" ||
    !Array.isArray(question.options)
  ) {
    throw new Error("Scenario oracle requires public id/title/options fields");
  }
  const result =
    pythonAnswer(question.title) ??
    sqlAnswer(question.title) ??
    httpAnswer(question.title);
  if (result === undefined)
    throw new Error(`No public scenario oracle for visible title/${grade}`);

  const answer = question.options.find((option) => {
    try {
      return sameJson(JSON.parse(option), result);
    } catch {
      return false;
    }
  });
  if (answer === undefined)
    throw new Error("Public-title oracle produced an unissued result");
  return answer;
}
