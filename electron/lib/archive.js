'use strict';

/**
 * Archive extraction for the setup assets. Uses the OS `tar`, which reads both
 * .zip and .tar.gz on Windows 10+ and macOS, so no unzip dependency ships.
 */

const fs = require('fs');

const { runStream } = require('./exec');

/** Extract a .zip (Neo4j / JRE / API bundle). */
async function extractZip(archivePath, destDir, onLine = () => {}) {
  fs.mkdirSync(destDir, { recursive: true });
  const { code } = await runStream('tar', ['-xf', archivePath, '-C', destDir], {}, onLine);
  if (code !== 0) throw new Error(`Failed to extract ${archivePath}`);
}

/** Extract a .tar.gz (the source corpus). */
async function extractTarGz(archivePath, destDir, onLine = () => {}) {
  fs.mkdirSync(destDir, { recursive: true });
  const { code } = await runStream('tar', ['-xzf', archivePath, '-C', destDir], {}, onLine);
  if (code !== 0) throw new Error(`Failed to extract ${archivePath}`);
}

module.exports = { extractZip, extractTarGz };
