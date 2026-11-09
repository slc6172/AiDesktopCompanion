const test = require("node:test");
const assert = require("node:assert/strict");
const { makeIsAppUrl, permissionAllowed, originOf } = require("../electron/navguard.js");

const isApp = makeIsAppUrl("http://127.0.0.1:8000/");

test("only the program's own origin counts as the app", () => {
  assert.equal(isApp("http://127.0.0.1:8000/"), true);
  assert.equal(isApp("http://127.0.0.1:8000/static/x.js?a=1#b"), true);
  assert.equal(isApp("http://127.0.0.1:8001/"), false);          // another port
  assert.equal(isApp("https://127.0.0.1:8000/"), false);         // another scheme
  assert.equal(isApp("http://localhost:8000/"), false);          // same machine, other name: not the same origin
  assert.equal(isApp("http://127.0.0.1.evil.com:8000/"), false);
  assert.equal(isApp("http://127.0.0.1:8000@evil.com/"), false); // userinfo trick: the host is evil.com
  assert.equal(isApp("https://evil.com/"), false);
});

test("things that are not http(s) addresses are never the app", () => {
  for (const url of ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,hi", "about:blank", "", undefined, null, 5, "not a url"]) {
    assert.equal(isApp(url), false, String(url));
  }
  assert.equal(originOf("file:///x"), null);
});

test("a guard built from a broken app address lets nothing through", () => {
  const none = makeIsAppUrl("not a url");
  assert.equal(none("http://127.0.0.1:8000/"), false);
  assert.equal(none("not a url"), false);
});

test("the microphone is allowed for the app's page only; every other permission is refused", () => {
  assert.equal(permissionAllowed("media", "http://127.0.0.1:8000/", isApp), true);
  assert.equal(permissionAllowed("media", "http://127.0.0.1:8000", isApp), true);   // an origin without a path, as the check handler gets it
  assert.equal(permissionAllowed("media", "https://evil.com/", isApp), false);
  assert.equal(permissionAllowed("notifications", "http://127.0.0.1:8000/", isApp), false);
  assert.equal(permissionAllowed("geolocation", "http://127.0.0.1:8000/", isApp), false);
  assert.equal(permissionAllowed("media", undefined, isApp), false);
});
