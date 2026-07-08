'use strict';

/**
 * Streaming HTTP(S) downloader with progress reporting, redirect handling,
 * resume-free caching, and optional SHA-256 verification. Used by the wizard to
 * fetch installers and the heavy release assets (image tar, snapshot, corpus).
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const https = require('https');
const http = require('http');

/**
 * Download `url` to `destPath`, reporting progress as a fraction (0..1) plus
 * transferred/total bytes. Follows redirects. Writes to a .part file and renames
 * on success so a crash never leaves a truncated file looking complete.
 *
 * @param {(p:{fraction:number|null, transferred:number, total:number|null})=>void} onProgress
 * @returns {Promise<string>} the destPath
 */
function downloadFile(url, destPath, onProgress = () => {}, redirectsLeft = 5) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(destPath), { recursive: true });
    const lib = url.startsWith('http:') ? http : https;
    const req = lib.get(url, (res) => {
      const { statusCode, headers } = res;
      if (statusCode >= 300 && statusCode < 400 && headers.location) {
        res.resume();
        if (redirectsLeft <= 0) return reject(new Error(`Too many redirects for ${url}`));
        const next = new URL(headers.location, url).toString();
        return resolve(downloadFile(next, destPath, onProgress, redirectsLeft - 1));
      }
      if (statusCode !== 200) {
        res.resume();
        return reject(new Error(`GET ${url} failed: HTTP ${statusCode}`));
      }
      const total = headers['content-length'] ? parseInt(headers['content-length'], 10) : null;
      let transferred = 0;
      const partPath = `${destPath}.part`;
      const out = fs.createWriteStream(partPath);
      res.on('data', (chunk) => {
        transferred += chunk.length;
        onProgress({ fraction: total ? transferred / total : null, transferred, total });
      });
      res.pipe(out);
      out.on('finish', () => out.close(() => {
        fs.renameSync(partPath, destPath);
        resolve(destPath);
      }));
      out.on('error', reject);
    });
    req.on('error', reject);
  });
}

/** Compute the SHA-256 hex digest of a file. */
function sha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const stream = fs.createReadStream(filePath);
    stream.on('data', (d) => hash.update(d));
    stream.on('end', () => resolve(hash.digest('hex')));
    stream.on('error', reject);
  });
}

/**
 * Download only if the cached file is missing or its checksum doesn't match.
 * @param {{url:string, dest:string, sha256?:string}} asset
 */
async function ensureAsset(asset, onProgress = () => {}) {
  const { url, dest, sha256: expected } = asset;
  if (fs.existsSync(dest)) {
    if (!expected || (await sha256(dest)) === expected) {
      onProgress({ fraction: 1, transferred: fs.statSync(dest).size, total: fs.statSync(dest).size });
      return dest;
    }
    fs.rmSync(dest); // stale/corrupt — re-download
  }
  await downloadFile(url, dest, onProgress);
  if (expected) {
    const actual = await sha256(dest);
    if (actual !== expected) {
      fs.rmSync(dest);
      throw new Error(`Checksum mismatch for ${url}: expected ${expected}, got ${actual}`);
    }
  }
  return dest;
}

module.exports = { downloadFile, sha256, ensureAsset };
