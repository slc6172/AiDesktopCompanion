// 視窗只該停在本機伺服器的頁面上:導覽、開新視窗、權限(麥克風)都以「是不是這個網站」為準。
// 純函式,不依賴 Electron,所以 tests_js/navguard.test.js 可以直接測。
"use strict";

function originOf(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.origin : null;
  } catch {
    return null;
  }
}

// appUrl 是程式自己的網址(例如 http://127.0.0.1:8000/)。回傳一個判斷函式:url 是否屬於同一個 origin。
function makeIsAppUrl(appUrl) {
  const appOrigin = originOf(appUrl);
  return (url) => appOrigin !== null && originOf(url) === appOrigin;
}

// 權限:只有本程式的頁面可以用麥克風/相機("media"),其他權限一律拒絕。
function permissionAllowed(permission, requestingUrl, isAppUrl) {
  return permission === "media" && isAppUrl(requestingUrl);
}

module.exports = { originOf, makeIsAppUrl, permissionAllowed };
