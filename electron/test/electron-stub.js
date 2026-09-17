'use strict';

/**
 * Makes `require('electron')` return a usable stub, so modules that reach
 * Electron's `app` for filesystem locations can be unit-tested under plain
 * `node --test`.
 *
 * Why this is needed: `lib/paths.js` does `const { app } = require('electron')`
 * at module scope. Outside Electron that require resolves to the npm package,
 * whose export is the *path string* to the binary — so `app` is `undefined` and
 * every `paths.*()` call throws. Pre-seeding the module cache with a fake `app`
 * fixes that without touching production code.
 *
 * Not named `*.test.js`, so `npm test`'s glob does not pick it up as a suite.
 *
 * Call `stubElectron()` BEFORE requiring anything that pulls in `lib/paths.js`.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

/**
 * @param {{userData?: string}} [opts] userData dir the fake `app` reports;
 *   defaults to a fresh temp dir.
 * @returns {{userData: string}} the directory the stub hands out.
 */
function stubElectron({ userData } = {}) {
  const dir = userData || fs.mkdtempSync(path.join(os.tmpdir(), 'emb-userdata-'));
  const id = require.resolve('electron');
  require.cache[id] = {
    id,
    filename: id,
    loaded: true,
    exports: {
      app: {
        isPackaged: false,
        getPath: (name) => (name === 'exe' ? path.join(dir, 'app.exe') : dir),
      },
    },
  };
  return { userData: dir };
}

module.exports = { stubElectron };
